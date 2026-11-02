"""Build private, tenant-local retrieval cases and evaluate BM25/PPR offline.

No LLM or embedding provider is called. Gold chunk IDs come only from existing
tenant-validated catalog-to-chunk mappings; generated cases are provisional
until a domain reviewer confirms that each mapped source answers the query.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.database.platform_session import PlatformSessionLocal
from app.database.tenant_session import tenant_session
from app.models.business_setting import BusinessSetting
from app.models.document import Document, DocumentChunk
from app.models.industry_modules import AppointmentService
from app.models.platform_control import TenantRegistry
from app.models.recommendation_catalog import RecommendationCatalogChunkMapping, RecommendationCatalogEntry
from app.models.sales import Product
from app.core.config import settings
from app.rag.embedder import _embed_with_gemini
from app.rag import retriever as retriever_module
from app.rag.retriever import (
    _diverse_candidates,
    _personalized_pagerank_rerank,
    _retrieve_lexical,
)
from app.tenancy.schema import schema_name_for, validate_schema_name


_ACTIVE_STATES = {"active", "ready", "disabled"}
_INDUSTRY_KEYS = {
    "industry", "industry_type", "industry_module", "business_industry",
    "business_type", "business_category", "vertical",
}
_TOP_K = 5


def _fold(value: object) -> str:
    raw = unicodedata.normalize("NFKD", str(value or "").casefold())
    return " ".join("".join(char for char in raw if not unicodedata.combining(char)).split())


def _registries() -> list[tuple[int, str]]:
    with PlatformSessionLocal() as db:
        rows = db.scalars(select(TenantRegistry).order_by(TenantRegistry.business_id)).all()
        result = []
        for row in rows:
            schema = validate_schema_name(row.schema_name)
            if schema != schema_name_for(int(row.business_id)):
                raise ValueError(f"tenant registry schema mismatch for business {row.business_id}")
            if str(row.state).casefold() in _ACTIVE_STATES:
                result.append((int(row.business_id), schema))
        return result


def _industry(db, business_id: int) -> tuple[str, str | None]:
    settings = db.scalars(
        select(BusinessSetting).where(
            BusinessSetting.business_id == business_id,
            BusinessSetting.key.in_(_INDUSTRY_KEYS),
        ).order_by(BusinessSetting.key)
    ).all()
    for row in settings:
        value = str(row.value or "").strip()
        if value:
            return value[:100], row.key
    return "unclassified", None


def _gold_rows(db, business_id: int, industry: str, industry_key: str | None) -> list[dict]:
    entries = db.scalars(
        select(RecommendationCatalogEntry).where(
            RecommendationCatalogEntry.business_id == business_id,
            RecommendationCatalogEntry.object_type == "product",
        ).order_by(RecommendationCatalogEntry.id)
    ).all()
    cases = []
    for entry in entries:
        if not entry.external_id.isdigit():
            continue
        product = db.scalar(select(Product).where(
            Product.id == int(entry.external_id), Product.business_id == business_id,
        ))
        if product is None:
            continue
        chunk_ids = db.scalars(
            select(RecommendationCatalogChunkMapping.document_chunk_id)
            .join(DocumentChunk, DocumentChunk.id == RecommendationCatalogChunkMapping.document_chunk_id)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                RecommendationCatalogChunkMapping.catalog_entry_id == entry.id,
                Document.business_id == business_id,
                Document.status == "ready",
            )
            .order_by(RecommendationCatalogChunkMapping.document_chunk_id)
        ).all()
        if not chunk_ids:
            continue
        cases.append({
            "id": f"shop-{business_id}-product-{product.id}",
            "business_id": business_id,
            "industry": industry,
            "industry_setting_key": industry_key,
            "object_type": "product",
            "query": f"Thông tin về sản phẩm {product.name} là gì?",
            "expected_chunk_ids": [int(value) for value in chunk_ids],
            "label_method": "tenant_validated_catalog_chunk_mapping",
            "label_status": "provisional_requires_domain_review",
        })
    return cases


def _rank_metrics(expected_ids: set[int], ranked_ids: list[int]) -> dict[str, float]:
    top = ranked_ids[:_TOP_K]
    found = [int(value in expected_ids) for value in top]
    first = next((index for index, hit in enumerate(found, start=1) if hit), None)
    dcg = sum(hit / math.log2(index + 2) for index, hit in enumerate(found))
    ideal = sum(1 / math.log2(index + 2) for index in range(min(len(expected_ids), _TOP_K)))
    return {
        "hit_at_5": float(first is not None),
        "recall_at_5": sum(found) / max(1, len(expected_ids)),
        "mrr": 1 / first if first else 0.0,
        "ndcg_at_5": dcg / ideal if ideal else 0.0,
    }


def _aggregate(rows: list[dict]) -> dict:
    keys = ("hit_at_5", "recall_at_5", "mrr", "ndcg_at_5")
    return {
        "case_count": len(rows),
        **{key: round(sum(row[key] for row in rows) / max(1, len(rows)), 6) for key in keys},
    }


def run(output_dir: Path, *, with_gemini_embeddings: bool = False) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    cases: list[dict] = []
    shop_results = []
    industry_counts: Counter[str] = Counter()
    method_rows: dict[str, list[dict]] = defaultdict(list)
    by_shop: dict[int, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    tenant_cases_by_shop: dict[int, list[dict]] = {}
    for business_id, schema in _registries():
        with tenant_session(schema) as db:
            industry, industry_key = _industry(db, business_id)
            tenant_cases = _gold_rows(db, business_id, industry, industry_key)
            industry_counts[industry] += len(tenant_cases)
            tenant_cases_by_shop[business_id] = tenant_cases
            cases.extend(tenant_cases)

    embeddings: list[list[float]] = []
    embedding_cache_path = output_dir / ".query-embeddings.json"
    embedding_cache_hit = False
    embedding_generation_call_count = 0
    if with_gemini_embeddings and cases:
        if settings.EMBEDDING_PROVIDER.strip().casefold() != "gemini":
            raise ValueError("--with-gemini-embeddings requires EMBEDDING_PROVIDER=gemini")
        query_hashes = {
            case["id"]: hashlib.sha256(case["query"].encode("utf-8")).hexdigest()
            for case in cases
        }
        if embedding_cache_path.exists():
            cached = json.loads(embedding_cache_path.read_text(encoding="utf-8"))
            if (cached.get("model") == settings.EMBEDDING_MODEL
                    and cached.get("dimension") == settings.EMBEDDING_DIMENSION
                    and cached.get("query_hashes") == query_hashes):
                embeddings = [cached["vectors"][case["id"]] for case in cases]
                embedding_cache_hit = True
                embedding_generation_call_count = int(cached.get("embedding_generation_call_count", 1))
        if not embeddings:
            embeddings = _embed_with_gemini(
                [case["query"] for case in cases],
                settings.EMBEDDING_MODEL,
                task_type="RETRIEVAL_QUERY",
            )
            embedding_generation_call_count = (len(embeddings) + 99) // 100
        if len(embeddings) != len(cases):
            raise ValueError("Gemini returned a different number of query embeddings than cases")
        if not embedding_cache_hit:
            embedding_cache_path.write_text(json.dumps({
                "model": settings.EMBEDDING_MODEL,
                "dimension": settings.EMBEDDING_DIMENSION,
                "embedding_generation_call_count": embedding_generation_call_count,
                "query_hashes": query_hashes,
                "vectors": {case["id"]: embeddings[index] for index, case in enumerate(cases)},
            }), encoding="utf-8")

    vector_by_case = {case["id"]: embeddings[index] for index, case in enumerate(cases)}
    for business_id, schema in _registries():
        tenant_cases = tenant_cases_by_shop.get(business_id, [])
        with tenant_session(schema) as db:
            bm25_count = ppr_changed = vector_fallbacks = 0
            for case in tenant_cases:
                lexical = _retrieve_lexical(
                    case["query"], db, 50, business_id=business_id, query_topic="products",
                )
                bm25_ids = [item.chunk_id for item in lexical[:_TOP_K]]
                ppr_scores = [
                    item.ranking_score if item.ranking_score is not None else item.similarity
                    for item in lexical
                ]
                ppr_results = _diverse_candidates(
                    _personalized_pagerank_rerank(lexical, ppr_scores),
                    _TOP_K,
                    max_per_document=4,
                )
                ppr_ids = [item.chunk_id for item in ppr_results[:_TOP_K]]
                expected = set(case["expected_chunk_ids"])
                bm25 = _rank_metrics(expected, bm25_ids)
                ppr = _rank_metrics(expected, ppr_ids)
                case["bm25"] = bm25
                case["bm25_plus_ppr"] = ppr
                case["bm25_top_chunk_ids"] = bm25_ids
                case["bm25_plus_ppr_top_chunk_ids"] = ppr_ids
                method_rows["bm25_only"].append(bm25)
                method_rows["bm25_plus_ppr_lexical_fallback"].append(ppr)
                by_shop[business_id]["bm25_only"].append(bm25)
                by_shop[business_id]["bm25_plus_ppr_lexical_fallback"].append(ppr)
                if with_gemini_embeddings:
                    diagnostics = {}
                    hybrid_results = retriever_module.retrieve(
                        case["query"], db, business_id=business_id,
                        top_k=_TOP_K, query_embedding=vector_by_case[case["id"]],
                        diagnostics=diagnostics,
                        retrieval_mode="hybrid",
                        enable_ppr=True,
                    )
                    hybrid_ids = [item.chunk_id for item in hybrid_results]
                    hybrid = _rank_metrics(expected, hybrid_ids)
                    case["gemini_bm25_rrf_ppr"] = hybrid
                    case["gemini_bm25_rrf_ppr_top_chunk_ids"] = hybrid_ids
                    case["retrieval_mode"] = diagnostics.get("retrieval_mode")
                    case["retrieval_fallback_stage"] = diagnostics.get("retrieval_fallback_stage")
                    method_rows["gemini_bm25_rrf_ppr"].append(hybrid)
                    by_shop[business_id]["gemini_bm25_rrf_ppr"].append(hybrid)
                    vector_fallbacks += diagnostics.get("retrieval_mode") != "hybrid"
                    original_lexical = retriever_module._retrieve_lexical
                    try:
                        no_ppr_results = retriever_module.retrieve(
                            case["query"], db, business_id=business_id,
                            top_k=_TOP_K, query_embedding=vector_by_case[case["id"]],
                            retrieval_mode="hybrid",
                            enable_ppr=False,
                        )
                        no_ppr_ids = [item.chunk_id for item in no_ppr_results]
                        no_ppr = _rank_metrics(expected, no_ppr_ids)
                        case["gemini_bm25_rrf_no_ppr"] = no_ppr
                        case["gemini_bm25_rrf_no_ppr_top_chunk_ids"] = no_ppr_ids
                        method_rows["gemini_bm25_rrf_no_ppr"].append(no_ppr)
                        by_shop[business_id]["gemini_bm25_rrf_no_ppr"].append(no_ppr)

                        retriever_module._retrieve_lexical = lambda *args, **kwargs: []
                        vector_results = retriever_module.retrieve(
                            case["query"], db, business_id=business_id,
                            top_k=_TOP_K, query_embedding=vector_by_case[case["id"]],
                            retrieval_mode="hybrid",
                            enable_ppr=False,
                        )
                        vector_ids = [item.chunk_id for item in vector_results]
                        vector_metrics = _rank_metrics(expected, vector_ids)
                        case["gemini_vector_only"] = vector_metrics
                        case["gemini_vector_only_top_chunk_ids"] = vector_ids
                        method_rows["gemini_vector_only"].append(vector_metrics)
                        by_shop[business_id]["gemini_vector_only"].append(vector_metrics)
                    finally:
                        retriever_module._retrieve_lexical = original_lexical
                bm25_count += bool(bm25_ids)
                ppr_changed += bm25_ids != ppr_ids
            shop_results.append({
                "business_id": business_id,
                "industry": industry,
                "case_count": len(tenant_cases),
                "queries_with_bm25_results": bm25_count,
                "ppr_order_changed_count": ppr_changed,
                "gemini_hybrid_fallback_count": vector_fallbacks if with_gemini_embeddings else None,
                "bm25_only": _aggregate([row["bm25"] for row in tenant_cases]),
                "bm25_plus_ppr_lexical_fallback": _aggregate([row["bm25_plus_ppr"] for row in tenant_cases]),
                **({"gemini_bm25_rrf_ppr": _aggregate([row["gemini_bm25_rrf_ppr"] for row in tenant_cases])}
                   if with_gemini_embeddings else {}),
                **({
                    "gemini_bm25_rrf_no_ppr": _aggregate([row["gemini_bm25_rrf_no_ppr"] for row in tenant_cases]),
                    "gemini_vector_only": _aggregate([row["gemini_vector_only"] for row in tenant_cases]),
                } if with_gemini_embeddings else {}),
            })

    case_path = output_dir / "industry-retrieval-evaluation-set.jsonl"
    case_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in cases), encoding="utf-8")
    review_path = output_dir / "industry-rag-answer-human-review.csv"
    with review_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=[
            "case_id", "business_id", "industry", "query", "expected_chunk_ids",
            "retrieved_chunk_ids", "answer_text", "source_support_1_to_5",
            "factual_correctness_1_to_5", "hallucination_yes_no",
            "should_handoff_yes_no", "reviewer_notes",
        ])
        writer.writeheader()
        for case in cases:
            writer.writerow({
                "case_id": case["id"],
                "business_id": case["business_id"],
                "industry": case["industry"],
                "query": case["query"],
                "expected_chunk_ids": ",".join(map(str, case["expected_chunk_ids"])),
                "retrieved_chunk_ids": ",".join(map(str, case.get(
                    "gemini_bm25_rrf_ppr_top_chunk_ids",
                    case["bm25_plus_ppr_top_chunk_ids"],
                ))),
            })

    report = {
        "status": "completed" if cases else "no_labeled_cases",
        "run_mode": ("local_postgresql_gemini_embedding_cache_reused" if embedding_cache_hit else "local_postgresql_one_batched_gemini_embedding_call") if with_gemini_embeddings else "local_postgresql_offline_no_llm_no_embedding_api",
        "embedding_model": settings.EMBEDDING_MODEL if with_gemini_embeddings else None,
        "embedding_dimension": settings.EMBEDDING_DIMENSION if with_gemini_embeddings else None,
        "embedding_api_call_count_this_run": (0 if embedding_cache_hit else embedding_generation_call_count) if with_gemini_embeddings else 0,
        "embedding_generation_api_call_count": embedding_generation_call_count if with_gemini_embeddings else 0,
        "embedding_cache_hit": embedding_cache_hit,
        "tenant_count": len(shop_results),
        "labeled_case_count": len(cases),
        "industry_case_counts": dict(sorted(industry_counts.items())),
        "methods": {
            name: _aggregate(rows) for name, rows in method_rows.items()
        },
        "shops": shop_results,
        "human_answer_review": {
            "status": "pending_reviewer_and_model_answers",
            "template_rows": len(cases),
            "csv_filename": review_path.name,
        },
        "limits": [
            "Cases cover only products with tenant-validated catalog-to-ready-chunk mappings; services/rentals without mappings are excluded.",
            "Machine-generated labels are provisional until a domain reviewer confirms the mapped source answers the query.",
            "Metrics compare BM25 order to BM25 candidates reranked by the production PPR helper; no dense embeddings or two-list RRF were run.",
            "Because there is no vector list in this offline run, single-list RRF is rank-preserving and cannot be credited as an evaluated gain.",
            "No LLM answer was generated; the CSV is a human review queue, not a completed answer-quality evaluation.",
            "No cross-encoder or LightFM model was trained or enabled.",
        ],
    }
    if with_gemini_embeddings:
        report["limits"].remove("Metrics compare BM25 order to BM25 candidates reranked by the production PPR helper; no dense embeddings or two-list RRF were run.")
        report["limits"].remove("Because there is no vector list in this offline run, single-list RRF is rank-preserving and cannot be credited as an evaluated gain.")
        report["limits"].append("Gemini query embeddings were generated once in a batch or read from a local temporary cache; dense retrieval and production RRF/PPR were run against the local tenant databases.")
    report_path = output_dir / "rag-retrieval-evaluation.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"report": report, "paths": {
        "report": str(report_path), "cases": str(case_path), "human_review": str(review_path),
    }}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--with-gemini-embeddings", action="store_true", help="make one batched Gemini embedding request for the labeled queries")
    args = parser.parse_args()
    print(json.dumps(run(args.output_dir, with_gemini_embeddings=args.with_gemini_embeddings), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
