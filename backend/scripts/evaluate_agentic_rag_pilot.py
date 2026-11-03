"""Compare retrieval-only and bounded corrective RAG on the same saved pilot cases."""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import statistics
import sys
import time
import unicodedata

from sqlalchemy import select, text as sa_text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.database.platform_session import PlatformSessionLocal
from app.database.tenant_session import tenant_session
from app.models.platform_control import TenantRegistry
from app.rag.agentic_controller import corrective_query, evidence_quality, retrieval_is_weak
from app.rag.catalog_filters import extract_query_hard_filters
from app.rag.embedder import _embed_with_gemini
from app.rag.retriever import retrieve, _retry_retrieval_mode
from app.tenancy.schema import schema_name_for, validate_schema_name


TOP_K = 5


def _metrics(expected_ids: set[int], ranked_ids: list[int]) -> dict:
    found = [int(item in expected_ids) for item in ranked_ids[:TOP_K]]
    rank = next((index for index, hit in enumerate(found, 1) if hit), None)
    dcg = sum(hit / math.log2(index + 2) for index, hit in enumerate(found))
    ideal = sum(1 / math.log2(index + 2) for index in range(min(len(expected_ids), TOP_K)))
    return {
        "hit_at_5": float(rank is not None),
        "recall_at_5": sum(found) / max(1, len(expected_ids)),
        "mrr": 1 / rank if rank else 0.0,
        "ndcg_at_5": dcg / ideal if ideal else 0.0,
    }


def _aggregate(rows: list[dict]) -> dict:
    fields = ("hit_at_5", "recall_at_5", "mrr", "ndcg_at_5")
    scored = [row for row in rows if row.get("scored_positive", True)]
    return {
        "cases": len(rows),
        "scored_positive_cases": len(scored),
        **{field: round(statistics.mean(row[field] for row in scored), 6) if scored else None for field in fields},
        "p50_latency_ms": round(statistics.median(row["latency_ms"] for row in rows), 2) if rows else 0.0,
        "p95_latency_ms": round(sorted(row["latency_ms"] for row in rows)[math.ceil(len(rows) * .95) - 1], 2) if rows else 0.0,
    }


def _tokens(text: str) -> set[str]:
    folded = unicodedata.normalize("NFKD", str(text or "").casefold().replace("đ", "d"))
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    return set(re.findall(r"[a-z0-9]+", folded))


def _resolve_expected_chunk_ids(db, business_id: int, case: dict) -> tuple[set[int], str, float | None]:
    """Remap stale integer labels using the saved source passage and filename."""
    raw_ids = set(map(int, case.get("expected_chunk_ids") or []))
    if not raw_ids:
        status = str(case.get("label_status") or "")
        if "negative_probe" in status or "coverage_probe" in status:
            return set(), "reviewed_negative_probe", None
        return set(), "no_retrieval_gold", None

    source_name = str(case.get("source_evidence") or "").strip()
    reference = str(case.get("source_chunk_text") or "").strip()
    expected_tokens = _tokens(reference)
    if not source_name or not expected_tokens:
        return set(), "unresolved_missing_source_reference", None

    rows = db.execute(sa_text("""
        SELECT dc.id, dc.content
        FROM document_chunks dc
        JOIN documents d ON d.id = dc.document_id
        WHERE d.business_id = :business_id AND d.status = 'ready'
          AND lower(d.filename) LIKE :source_name
    """), {"business_id": business_id, "source_name": f"%{source_name.casefold()}%"}).fetchall()
    ranked = []
    for row in rows:
        candidate_tokens = _tokens(row._mapping["content"])
        if not candidate_tokens:
            continue
        overlap = len(expected_tokens & candidate_tokens)
        precision = overlap / len(candidate_tokens)
        recall = overlap / len(expected_tokens)
        score = (2 * precision * recall / (precision + recall)) if precision + recall else 0.0
        ranked.append((score, int(row._mapping["id"])))
    ranked.sort(reverse=True)
    if not ranked or ranked[0][0] < 0.85:
        return set(), "unresolved_stale_chunk_ids", round(ranked[0][0], 4) if ranked else None
    return {ranked[0][1]}, "mapped_from_source_text", round(ranked[0][0], 4)


def _tenant_schemas(business_ids: set[int]) -> dict[int, str]:
    with PlatformSessionLocal() as db:
        rows = db.scalars(select(TenantRegistry).where(TenantRegistry.business_id.in_(business_ids))).all()
        result = {}
        for row in rows:
            business_id = int(row.business_id)
            schema = validate_schema_name(row.schema_name)
            if schema != schema_name_for(business_id):
                raise ValueError(f"Tenant registry schema mismatch for shop {business_id}")
            result[business_id] = schema
    missing = business_ids - result.keys()
    if missing:
        raise ValueError(f"No tenant schema registered for shops {sorted(missing)}")
    return result


def run(cases_path: Path, output_path: Path, *, gemini: bool) -> dict:
    raw_cases = json.loads(cases_path.read_text(encoding="utf-8"))
    cases = raw_cases.get("cases", []) if isinstance(raw_cases, dict) else raw_cases
    if not cases:
        raise ValueError("Pilot case set is empty")
    business_ids = {int(case["business_id"]) for case in cases}
    schemas = _tenant_schemas(business_ids)
    query_vectors = {}
    embedding_call_count = 0
    if gemini:
        texts = list(dict.fromkeys(
            text for case in cases for text in (case["query"], corrective_query(case["query"])) if text
        ))
        if settings.EMBEDDING_PROVIDER.strip().casefold() != "gemini":
            raise ValueError("Hybrid pilot requires EMBEDDING_PROVIDER=gemini")
        vectors = _embed_with_gemini(texts, settings.EMBEDDING_MODEL, task_type="RETRIEVAL_QUERY")
        query_vectors = dict(zip(texts, vectors))
        embedding_call_count = (len(texts) + 99) // 100

    all_rows = defaultdict(list)
    per_shop = defaultdict(lambda: defaultdict(list))
    per_type = defaultdict(lambda: defaultdict(list))
    case_rows = []
    retry_count = defaultdict(int)
    tool_call_count = defaultdict(int)
    no_answer_false_positives = defaultdict(int)
    no_answer_case_counts = defaultdict(int)
    label_resolution_counts = defaultdict(int)

    for case in cases:
        business_id = int(case["business_id"])
        query = str(case["query"])
        raw_expected = set(map(int, case.get("expected_chunk_ids") or []))
        expected: set[int] = set()
        resolution_status = None
        reference_match_score = None
        scored_positive = False
        scored_negative = False
        hard_filters = case.get("hard_filters") or extract_query_hard_filters(query)
        case_detail = {
            "id": case["id"],
            "business_id": business_id,
            "case_type": case.get("case_type"),
            "expected_chunk_ids_original": sorted(raw_expected),
            "arms": {},
        }
        for mode in (("bm25", "hybrid") if gemini else ("bm25",)):
            arm_names = ((f"{mode}_baseline", f"{mode}_agentic") if mode == "bm25"
                         else ("hybrid_no_ppr_baseline", "hybrid_no_ppr_agentic"))
            diagnostics = {}
            arguments = {
                "query": query,
                "db": None,
                "business_id": business_id,
                "top_k": TOP_K,
                "hard_filters": hard_filters,
                "retrieval_mode": mode,
                "enable_ppr": False,
                "diagnostics": diagnostics,
            }
            if gemini:
                arguments["query_embedding"] = query_vectors[query]
            with tenant_session(schemas[business_id]) as db:
                if resolution_status is None:
                    expected, resolution_status, reference_match_score = _resolve_expected_chunk_ids(
                        db, business_id, case,
                    )
                    scored_positive = bool(raw_expected and expected)
                    scored_negative = not raw_expected and resolution_status == "reviewed_negative_probe"
                    label_resolution_counts[resolution_status] += 1
                    case_detail.update(
                        expected_chunk_ids_resolved=sorted(expected),
                        label_resolution_status=resolution_status,
                        reference_match_score=reference_match_score,
                        scored_positive=scored_positive,
                        scored_negative=scored_negative,
                    )
                arguments["db"] = db
                started = time.perf_counter()
                baseline_chunks = retrieve(**arguments)
                baseline_latency = (time.perf_counter() - started) * 1000
                baseline_metrics = _metrics(expected, [chunk.chunk_id for chunk in baseline_chunks]) if scored_positive else None
                baseline_row = {**(baseline_metrics or {}), "latency_ms": baseline_latency,
                                "scored_positive": scored_positive}
                all_rows[arm_names[0]].append(baseline_row)
                per_shop[business_id][arm_names[0]].append(baseline_row)
                per_type[str(case.get("case_type") or "unclassified")][arm_names[0]].append(baseline_row)
                tool_call_count[arm_names[0]] += 1

                started = time.perf_counter()
                selected_chunks = baseline_chunks
                retried = False
                retry_latency = 0.0
                retry_diagnostics = {}
                retry = corrective_query(query)
                if retrieval_is_weak(baseline_chunks, settings.RAG_AGENTIC_RETRY_THRESHOLD) and retry != query:
                    retry_args = {
                        **arguments,
                        "query": retry,
                        "diagnostics": retry_diagnostics,
                        "retrieval_mode": _retry_retrieval_mode(mode, diagnostics),
                    }
                    if gemini:
                        retry_args["query_embedding"] = query_vectors[retry]
                    retry_started = time.perf_counter()
                    retry_chunks = retrieve(**retry_args)
                    retry_latency = (time.perf_counter() - retry_started) * 1000
                    retried = True
                    retry_count[arm_names[1]] += 1
                    tool_call_count[arm_names[1]] += 1
                    if evidence_quality(retry_chunks) > evidence_quality(baseline_chunks):
                        selected_chunks = retry_chunks
                agentic_elapsed = (time.perf_counter() - started) * 1000
                agentic_total_latency = baseline_latency + agentic_elapsed
                agentic_metrics = _metrics(expected, [chunk.chunk_id for chunk in selected_chunks]) if scored_positive else None
                agentic_row = {**(agentic_metrics or {}), "latency_ms": agentic_total_latency,
                               "scored_positive": scored_positive}
                all_rows[arm_names[1]].append(agentic_row)
                per_shop[business_id][arm_names[1]].append(agentic_row)
                per_type[str(case.get("case_type") or "unclassified")][arm_names[1]].append(agentic_row)
                tool_call_count[arm_names[1]] += 1
                if scored_negative:
                    no_answer_case_counts[arm_names[0]] += 1
                    no_answer_case_counts[arm_names[1]] += 1
                if scored_negative and selected_chunks:
                    no_answer_false_positives[arm_names[1]] += 1
                if scored_negative and baseline_chunks:
                    no_answer_false_positives[arm_names[0]] += 1
                case_detail["arms"][arm_names[0]] = {
                    "metrics": baseline_metrics,
                    "latency_ms": round(baseline_latency, 2),
                    "retrieved_ids": [chunk.chunk_id for chunk in baseline_chunks],
                    "negative_probe_false_positive": bool(scored_negative and baseline_chunks),
                    "fallback_stage": diagnostics.get("retrieval_fallback_stage"),
                }
                case_detail["arms"][arm_names[1]] = {
                    "metrics": agentic_metrics,
                    "latency_ms": round(agentic_total_latency, 2),
                    "retried": retried,
                    "read_tool_calls": 1 + int(retried),
                    "retry_latency_ms": round(retry_latency, 2),
                    "retrieved_ids": [chunk.chunk_id for chunk in selected_chunks],
                    "negative_probe_false_positive": bool(scored_negative and selected_chunks),
                    "fallback_stage": retry_diagnostics.get("retrieval_fallback_stage") if retried else diagnostics.get("retrieval_fallback_stage"),
                }
        case_rows.append(case_detail)

    arms = {name: _aggregate(rows) for name, rows in all_rows.items()}
    paired = {}
    for baseline, agentic in (("bm25_baseline", "bm25_agentic"), ("hybrid_no_ppr_baseline", "hybrid_no_ppr_agentic")):
        if baseline not in all_rows:
            continue
        wins = ties = losses = 0
        for row in case_rows:
            if not row.get("scored_positive"):
                continue
            before = row["arms"][baseline]["metrics"]["ndcg_at_5"]
            after = row["arms"][agentic]["metrics"]["ndcg_at_5"]
            wins += after > before
            losses += after < before
            ties += after == before
        paired[agentic] = {"wins": wins, "ties": ties, "losses": losses, "retry_cases": retry_count[agentic]}
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "same_case_set_retrieval_only_agentic_pilot",
        "case_file": cases_path.name,
        "case_count": len(cases),
        "scored_positive_case_count": sum(1 for row in case_rows if row.get("scored_positive")),
        "scored_negative_case_count": sum(1 for row in case_rows if row.get("scored_negative")),
        "unscored_case_count": sum(1 for row in case_rows if not row.get("scored_positive") and not row.get("scored_negative")),
        "label_resolution_status_counts": dict(label_resolution_counts),
        "label_status_counts": dict(__import__("collections").Counter(str(case.get("label_status") or "unlabeled") for case in cases)),
        "embedding": {"provider": settings.EMBEDDING_PROVIDER if gemini else None, "model": settings.EMBEDDING_MODEL if gemini else None,
                      "query_count": len(query_vectors), "api_batch_calls": embedding_call_count},
        "arms": arms,
        "paired_ndcg_changes": paired,
        "read_tool_calls": {
            name: {"total": count, "mean_per_case": round(count / len(cases), 3)}
            for name, count in tool_call_count.items()
        },
        "per_shop": {str(shop): {name: _aggregate(rows) for name, rows in arms_.items()} for shop, arms_ in per_shop.items()},
        "per_case_type": {kind: {name: _aggregate(rows) for name, rows in arms_.items()} for kind, arms_ in per_type.items()},
        "negative_probe_false_positives": {
            name: {
                "count": no_answer_false_positives[name],
                "cases": no_answer_case_counts[name],
                "rate": round(
                    no_answer_false_positives[name] / no_answer_case_counts[name], 6,
                ) if no_answer_case_counts[name] else None,
            }
            for name in set(no_answer_false_positives) | set(no_answer_case_counts)
        },
        "limitations": [
            "This evaluates retrieval only; no answer LLM is called, so it does not measure answer correctness, citation support, or response tokens.",
            "Pilot relevance labels are the saved case contracts and have not all been human reviewed.",
            "Latency excludes embedding batch generation and measures local retrieval calls.",
            "The controller performs one corrective retrieval at most; the production auto-reply also reads matching live catalog data separately.",
        ],
        "cases": case_rows,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    default_dir = Path(__file__).resolve().parents[1] / ".local-evaluation" / "rag-audit-20261102-self-check" / "postfix-20261102"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=default_dir / "bm25_serving-input.json")
    parser.add_argument("--output", type=Path, default=default_dir / "agentic-control-pilot-20261102.json")
    parser.add_argument("--with-hybrid", action="store_true", help="Also evaluate hybrid no-PPR; makes one batched Gemini query-embedding request.")
    args = parser.parse_args()
    report = run(args.cases, args.output, gemini=args.with_hybrid)
    print(json.dumps({"case_count": report["case_count"], "arms": report["arms"],
                      "paired_ndcg_changes": report["paired_ndcg_changes"],
                      "label_resolution_status_counts": report["label_resolution_status_counts"],
                      "negative_probe_false_positives": report["negative_probe_false_positives"]}, ensure_ascii=True))


if __name__ == "__main__":
    main()
