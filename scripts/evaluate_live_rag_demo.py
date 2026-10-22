#!/usr/bin/env python3
"""Run synthetic demo retrieval and answer evaluation in an isolated pgvector schema."""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import uuid
from collections import Counter
from unittest.mock import patch
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT if BACKEND_ROOT.is_dir() else PROJECT_ROOT))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document, DocumentChunk
from app.rag.answer_guard import has_valid_citations
from app.rag.embedder import embed_texts, embed_queries
from app.rag.llm_caller import call_llm
from app.rag.prompt_builder import build_prompt
from app.rag.retriever import retrieve
from app.rag.semantic_chunker import chunk_document, contextual_embedding_text
from app.rag.loader import load_document
from app.rag.topics import fold_topic_text

SOURCE_ALIASES = {
    "tenant_product_catalog": {"demo-products.vi-en.csv"},
    "tenant_product_catalog_or_approved_product_knowledge": {
        "demo-products.vi-en.csv", "demo-industry-playbook.vi-en.md",
    },
    "approved_tenant_delivery_policy": {"demo-support-policies.vi-en.md"},
    "approved_tenant_returns_warranty_policy": {"demo-support-policies.vi-en.md"},
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--skip-answers", action="store_true")
    parser.add_argument("--provider-interval", type=float, default=0,
                        help="Seconds between embedding batches and answer calls; respects provider rate limits.")
    parser.add_argument("--embedding-batch-size", type=int, default=50,
                        help="Document texts per embedding call (1-100).")
    parser.add_argument(
        "--lexical-only", action="store_true",
        help="Skip all embedding API calls and evaluate the app's lexical fallback path.",
    )
    parser.add_argument("--case-id", action="append", default=[], help="Repeat to evaluate selected case IDs only")
    parser.add_argument(
        "--require-full-vector", action="store_true",
        help="Exit with status 2 after writing the report if any case fell back from vector retrieval.",
    )
    args = parser.parse_args()
    if args.provider_interval < 0 or not 1 <= args.embedding_batch_size <= 100:
        parser.error("Interval must be nonnegative and embedding batch size must be between 1 and 100.")
    logging.basicConfig(level=logging.ERROR)
    if not args.lexical_only and not settings.embedding_api_keys:
        parser.error("Embedding provider has no configured key in the app runtime.")
    if not args.skip_answers and not settings.llm_api_keys and not settings.groq_api_keys and not settings.gemini_api_keys:
        parser.error("LLM provider has no configured key in the app runtime.")

    cases = [json.loads(line) for line in args.cases.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.case_id:
        selected = set(args.case_id)
        cases = [case for case in cases if case.get("id") in selected]
        missing = selected - {case.get("id") for case in cases}
        if missing:
            parser.error("Unknown case IDs: " + ", ".join(sorted(missing)))
    source_names = [
        "demo-store-profile.vi-en.md", "demo-products.vi-en.csv",
        "demo-support-policies.vi-en.md", "demo-industry-playbook.vi-en.md",
    ]
    docs = []
    all_chunks = []
    for filename in source_names:
        path = args.source_dir / filename
        content = load_document(path.read_bytes(), filename)
        chunks = chunk_document(content, filename)
        docs.append((filename, path.stat().st_size, chunks))
        all_chunks.extend((filename, chunk) for chunk in chunks)
    if args.lexical_only:
        print("Bỏ qua embedding API; chạy đúng nhánh tìm kiếm từ khóa dự phòng...", flush=True)
        vectors = [None] * len(all_chunks)
        query_vectors = [None] * len(cases)
    else:
        print(f"Tạo embedding cho {len(all_chunks)} đoạn tài liệu demo...", flush=True)
        vectors = []
        texts = [contextual_embedding_text(chunk) for _, chunk in all_chunks]
        for offset in range(0, len(texts), args.embedding_batch_size):
            if offset and args.provider_interval:
                time.sleep(args.provider_interval)
            vectors.extend(embed_texts(texts[offset:offset + args.embedding_batch_size]))
            print(f"Embedding tài liệu: {len(vectors)}/{len(texts)}", flush=True)
        if len(vectors) != len(all_chunks):
            raise RuntimeError("Số embedding trả về không khớp số đoạn tài liệu.")
        print(f"Tạo embedding theo lô cho {len(cases)} câu hỏi...", flush=True)
        if args.provider_interval:
            time.sleep(args.provider_interval)
        query_vectors = embed_queries([str(case["query"]) for case in cases])

    schema = "rag_eval_" + uuid.uuid4().hex[:16]
    engine = create_engine(settings.tenant_database_url, pool_pre_ping=True)
    connection = engine.connect()
    outer = connection.begin()
    db = None
    report_cases = []
    latency_retrieval = []
    latency_answer = []
    source_hits = expected_source_count = full_source_hits = evaluated_retrieval = 0
    hybrid_source_hits = hybrid_expected_source_count = hybrid_full_source_hits = hybrid_evaluated_cases = 0
    answer_count = citation_count = citation_cases = must_hits = must_total = forbidden_clean = 0
    provider_failures = Counter()
    retrieval_fallbacks = Counter()
    try:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
        Document.__table__.create(connection, checkfirst=False)
        DocumentChunk.__table__.create(connection, checkfirst=False)
        # The temporary table is tiny. Remove its freshly randomized HNSW graph
        # and force a sequential scan so repeated evaluations measure ranking
        # quality, not approximate-index graph layout.
        connection.execute(text("DROP INDEX IF EXISTS idx_document_chunks_embedding_hnsw"))
        connection.execute(text("SET LOCAL enable_indexscan = off"))
        connection.execute(text("SET LOCAL enable_bitmapscan = off"))
        db = Session(bind=connection, join_transaction_mode="create_savepoint")
        business_id = 889_000_000
        offset = 0
        by_name = {filename: (size, chunks) for filename, size, chunks in docs}
        document_ids = {}
        for filename in source_names:
            size, chunks = by_name[filename]
            doc = Document(business_id=business_id, filename=filename, file_type=Path(filename).suffix.lstrip("."),
                           file_size=size, status="ready", embedding_status="ready", chunk_count=len(chunks))
            db.add(doc)
            db.flush()
            document_ids[filename] = doc.id
            chunk_rows = []
            for chunk in chunks:
                current_filename, current_chunk = all_chunks[offset]
                assert current_filename == filename and current_chunk is chunk
                chunk_rows.append(DocumentChunk(
                    document_id=doc.id, content=chunk.content, chunk_index=chunk.index,
                    embedding=vectors[offset], metadata_=chunk.metadata,
                ))
                offset += 1
            db.add_all(chunk_rows)
        db.flush()

        for index, case in enumerate(cases, start=1):
            if index > 1 and not args.skip_answers and args.provider_interval:
                time.sleep(args.provider_interval)
            query = str(case["query"])
            started = time.perf_counter()
            diagnostics = {}
            if args.lexical_only:
                with patch("app.rag.retriever.embed_query", side_effect=RuntimeError("lexical-only evaluation")):
                    chunks = retrieve(query, db, business_id=business_id, top_k=5,
                                      query_embedding=None, diagnostics=diagnostics)
            else:
                chunks = retrieve(query, db, business_id=business_id, top_k=5,
                                  query_embedding=query_vectors[index - 1], diagnostics=diagnostics)
            fallback_stage = diagnostics.get("retrieval_fallback_stage")
            case_fallbacks = [f"{fallback_stage}:{diagnostics.get('retrieval_error_type')}"] if fallback_stage else []
            if fallback_stage:
                retrieval_fallbacks[fallback_stage] += 1
            latency_retrieval.append((time.perf_counter() - started) * 1000)
            found = {chunk.filename for chunk in chunks}
            expected = []
            for expected_name in case.get("expected_sources", []):
                allowed_names = SOURCE_ALIASES.get(expected_name, {expected_name})
                expected.extend(name for name in source_names if name in allowed_names and name not in expected)
            source_hits += sum(name in found for name in expected)
            expected_source_count += len(expected)
            full_source_hits += bool(expected) and all(name in found for name in expected)
            evaluated_retrieval += bool(expected)
            if expected and not case_fallbacks:
                hybrid_source_hits += sum(name in found for name in expected)
                hybrid_expected_source_count += len(expected)
                hybrid_full_source_hits += all(name in found for name in expected)
                hybrid_evaluated_cases += 1
            source_texts = [chunk.content for chunk in chunks]
            citation_required = case.get("citation_required", bool(expected))
            citation_cases += int(citation_required and not args.skip_answers)
            answer = ""
            answer_error = None
            answer_ms = None
            if not args.skip_answers and chunks:
                try:
                    started = time.perf_counter()
                    answer = call_llm(build_prompt(query, chunks))
                    answer_ms = round((time.perf_counter() - started) * 1000, 2)
                    latency_answer.append(answer_ms)
                    if not answer or not answer.strip():
                        raise RuntimeError("empty_llm_answer")
                    answer_count += 1
                    valid_citation = has_valid_citations(answer, source_texts, query=query)
                    if citation_required:
                        citation_count += int(valid_citation)
                    folded_answer = fold_topic_text(answer)
                    forbidden = [term for term in case.get("must_not_include", [])
                                 if fold_topic_text(term) in folded_answer]
                    forbidden_clean += int(not forbidden)
                    must = case.get("must_include", [])
                    must_total += len(must)
                    must_hits += sum(fold_topic_text(term) in folded_answer for term in must)
                except Exception as error:
                    answer_error = type(error).__name__
                    provider_failures[answer_error] += 1
            report_cases.append({
                "id": case.get("id"), "query": query,
                "expected_sources": expected,
                "retrieved_sources": [chunk.filename for chunk in chunks],
                "retrieved_chunk_ids": [chunk.chunk_id for chunk in chunks],
                "retrieved_contents": source_texts,
                "retrieved_metadata": [chunk.metadata for chunk in chunks],
                "answer": answer,
                "citation_required": case.get("citation_required", bool(expected)),
                "valid_citation_gate": has_valid_citations(answer, source_texts, query=query) if answer else False,
                "must_include": case.get("must_include", []),
                "must_not_include": case.get("must_not_include", []),
                "must_include_missing": [term for term in case.get("must_include", [])
                                         if fold_topic_text(term) not in fold_topic_text(answer)],
                "must_not_include_found": [term for term in case.get("must_not_include", [])
                                           if fold_topic_text(term) in fold_topic_text(answer)],
                "answer_error_type": answer_error,
                "retrieval_fallbacks": case_fallbacks,
                "retrieval_mode": diagnostics.get("retrieval_mode"),
                "retrieval_latency_ms": round(latency_retrieval[-1], 2),
                "answer_latency_ms": answer_ms,
            })
            print(f"Đã đánh giá {index}/{len(cases)}: {case.get('id')} · "
                  f"{'lỗi ' + answer_error if answer_error else 'có phản hồi' if answer else 'chỉ truy xuất'}", flush=True)

        fallback_case_count = sum(bool(item["retrieval_fallbacks"]) for item in report_cases)
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "status": "completed",
            "provider_interval_seconds": args.provider_interval,
            "mode": (
                "live_app_lexical_fallback_retrieval_only" if args.lexical_only and args.skip_answers
                else "live_app_lexical_fallback_with_configured_answer_provider" if args.lexical_only
                else "live_app_hybrid_pgvector_with_configured_providers"
            ),
            "vector_search": "disabled intentionally; evaluates the application's lexical fallback" if args.lexical_only else "exact sequential scan in temporary evaluation schema (index scans disabled)",
            "query_embedding_mode": "not used; no embedding API calls" if args.lexical_only else "batched RETRIEVAL_QUERY; same vectors as serving, no per-question provider call",
            "data_scope": "synthetic demo documents and synthetic evaluation prompts only",
            "provider": {
                "embedding": "not_used_lexical_only" if args.lexical_only else settings.EMBEDDING_PROVIDER,
                "embedding_model": None if args.lexical_only else settings.EMBEDDING_MODEL,
                "answer": "not_used" if args.skip_answers else settings.LLM_PROVIDER,
                "answer_model": None if args.skip_answers else settings.LLM_MODEL,
            },
            "temporary_schema_rolled_back": True,
            "source_files": source_names,
            "source_chunks": len(all_chunks),
            "retrieval": {
                "evaluated_cases": evaluated_retrieval,
                "expected_source_recall_at_5": round(source_hits / max(1, expected_source_count), 4),
                "all_expected_sources_in_top_5_rate": round(full_source_hits / max(1, evaluated_retrieval), 4),
                "mean_latency_ms": round(sum(latency_retrieval) / max(1, len(latency_retrieval)), 2),
                "fallback_cases": fallback_case_count,
                "fully_hybrid_cases": len(report_cases) - fallback_case_count,
                "fallback_events_by_stage": dict(retrieval_fallbacks),
                "usable_for_promotion": fallback_case_count == 0,
                "fully_hybrid_only": {
                    "evaluated_cases": hybrid_evaluated_cases,
                    "expected_source_recall_at_5": round(hybrid_source_hits / max(1, hybrid_expected_source_count), 4),
                    "all_expected_sources_in_top_5_rate": round(hybrid_full_source_hits / max(1, hybrid_evaluated_cases), 4),
                    "note": "Excludes every case that silently fell back to lexical retrieval; subset score alone is not a full-suite promotion gate.",
                },
            },
            "answers": {
                "attempted": answer_count + sum(provider_failures.values()),
                "generated": answer_count,
                "citation_gate_pass_rate": round(citation_count / max(1, citation_cases), 4),
                "citation_cases": citation_cases,
                "must_include_term_rate": round(must_hits / max(1, must_total), 4),
                "no_forbidden_term_rate": round(forbidden_clean / max(1, answer_count), 4),
                "mean_latency_ms": round(sum(latency_answer) / max(1, len(latency_answer)), 2),
                "provider_errors_by_type": dict(provider_failures),
                "citation_gate_note": "Checks citation IDs and monetary values against cited source text; does not prove every semantic claim.",
            },
            "cases": report_cases,
            "limitations": [
                "No live shop, customer, order, or social account was read or contacted.",
                "Synthetic policy and product facts must not be used for customer-facing replies.",
            "This harness calls the knowledge retriever directly; it does not exercise intent routing or CRM tools, so it cannot validate live product price, stock, order, or sales answers.",
                "Literal must-include checks and citation validation are useful gates, not full human semantic review.",
            ],
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({key: value for key, value in report.items() if key != "cases"}, ensure_ascii=False, indent=2), flush=True)
    finally:
        if db is not None:
            db.close()
        if outer.is_active:
            outer.rollback()
        connection.close()
        engine.dispose()
    return 2 if args.require_full_vector and fallback_case_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
