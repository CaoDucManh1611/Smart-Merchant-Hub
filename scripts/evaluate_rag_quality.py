"""Evaluate the 100-case router and the app retriever against the safe demo pack.

No customer records, live tenant database, embedding provider, LLM, or external
messaging channel is used. Retrieval runs through the current lexical fallback
in an isolated SQLite fixture; answer generation is intentionally not called.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from app.database.bases import TenantBase  # noqa: E402
from app.models.business import Business  # noqa: E402
from app.models.document import Document, DocumentChunk  # noqa: E402
from app.rag.loader import load_document  # noqa: E402
from app.rag.retriever import retrieve  # noqa: E402
from app.rag.semantic_chunker import chunk_document  # noqa: E402
from app.rag.topics import fold_topic_text, infer_document_topic  # noqa: E402
from evaluate_rag_set import expected_route  # noqa: E402


DEMO_SOURCE_FILES = (
    "demo-store-profile.vi-en.md",
    "demo-products.vi-en.csv",
    "demo-support-policies.vi-en.md",
    "demo-industry-playbook.vi-en.md",
)

ANSWER_CONTRACTS = {
    "lookup_product": "Tra đúng mã, tên và biến thể trong danh mục hiện hành; trả giá/tồn kho lấy từ dữ liệu shop. Nếu không khớp chính xác thì hỏi lại hoặc báo chưa tìm thấy, không tự suy đoán.",
    "lookup_product_catalog": "Chỉ liệt kê sản phẩm đang có trong danh mục của shop; không tự tạo sản phẩm hay khuyến mãi.",
    "lookup_sales": "Dùng đơn đã hoàn tất hoặc đã giao và thanh toán của đúng shop; nếu thiếu dữ liệu thì không bịa thứ hạng và chuyển nhân viên.",
    "lookup_order": "Chỉ tra đơn của khách đã xác thực trong CRM. Trả trạng thái từ bản ghi; nếu thiếu mã đơn hoặc chưa xác minh được khách thì hỏi lại/chuyển nhân viên.",
    "search_knowledge": "Trả lời ngắn gọn theo tài liệu đã được shop xác nhận. Nếu tài liệu không quy định hoặc mâu thuẫn, nói rõ chưa xác minh và chuyển nhân viên; không bịa chính sách.",
    "handoff": "Xác nhận đã nhận yêu cầu và chuyển nhân viên. Không nói rằng vấn đề đã được giải quyết nếu chưa có kết quả từ hệ thống/người phụ trách.",
    "clarify_product": "Hỏi ngắn gọn đúng thông tin còn thiếu (sản phẩm, mã, biến thể, đơn hàng hoặc ngữ cảnh); chưa báo giá/tồn kho khi chưa xác định được đối tượng.",
}


def expected_sources(case: dict) -> list[str]:
    action = case["expected_action"]
    topic = case["expected_topic"]
    if action in {"lookup_product", "lookup_product_catalog"}:
        return ["tenant_product_catalog"]
    if action == "lookup_sales":
        return ["tenant_completed_sales_orders"]
    if action == "lookup_order":
        return ["authenticated_customer_order_record"]
    if action == "handoff":
        return ["human_handoff_route", "relevant_safety_or_support_policy"]
    if action == "clarify_product":
        return ["conversation_context_or_customer_clarification"]
    if topic == "delivery":
        return ["approved_tenant_delivery_policy"]
    if topic == "returns":
        return ["approved_tenant_returns_warranty_policy"]
    if topic == "payment":
        return ["approved_tenant_payment_policy_or_verified_payment_record"]
    if topic == "safety":
        return ["tenant_privacy_safety_policy_or_authorized_tool"]
    if topic == "products":
        return ["tenant_product_catalog_or_approved_product_knowledge"]
    if topic == "orders":
        return ["authenticated_customer_order_record"]
    return ["approved_tenant_knowledge_base"]


def write_answer_key(cases: list[dict], path: Path) -> None:
    rows = []
    for case in cases:
        rows.append({
            "id": case["id"],
            "expected_action": case["expected_action"],
            "expected_sources": expected_sources(case),
            "reference_answer_contract": ANSWER_CONTRACTS[case["expected_action"]],
            "must_include": case.get("must_include", []),
            "must_not_include": case.get("must_not_include", []),
            "fixture_requirement": (
                "tenant_catalog_fixture" if case["expected_action"] in {"lookup_product", "lookup_product_catalog"}
                else "completed_sales_orders_fixture" if case["expected_action"] == "lookup_sales"
                else "authenticated_order_fixture" if case["expected_action"] == "lookup_order"
                else "approved_tenant_documents" if case["expected_action"] == "search_knowledge"
                else "none_for_routing_only"
            ),
        })
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def load_cases(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def prepare_demo_retriever():
    engine = create_engine("sqlite://")
    Business.metadata.create_all(engine)
    TenantBase.metadata.create_all(engine)
    db = Session(engine)
    business = Business(name="Isolated RAG evaluation", slug="rag-eval-isolated")
    db.add(business)
    db.flush()
    source_dir = ROOT / "knowledge_base"
    loaded_sources = []
    chunk_total = 0
    for filename in DEMO_SOURCE_FILES:
        path = source_dir / filename
        raw = path.read_bytes()
        content = load_document(raw, filename)
        topic = infer_document_topic(filename, content)
        chunks = chunk_document(content, filename, source_metadata={"topic": topic})
        document = Document(
            business_id=business.id,
            filename=filename,
            file_type=path.suffix.lstrip("."),
            file_size=len(raw),
            status="ready",
            chunk_count=len(chunks),
        )
        db.add(document)
        db.flush()
        db.add_all([
            DocumentChunk(
                document_id=document.id,
                content=chunk.content,
                chunk_index=chunk.index,
                metadata_=chunk.metadata,
            )
            for chunk in chunks
        ])
        loaded_sources.append(filename)
        chunk_total += len(chunks)
    db.commit()
    return engine, db, int(business.id), loaded_sources, chunk_total


def evaluate_demo_retrieval(cases: list[dict]) -> dict:
    engine, db, business_id, loaded_sources, chunk_total = prepare_demo_retriever()
    total_expected_sources = 0
    source_hits = 0
    complete_cases = 0
    evaluated_cases = 0
    evidence_requirements = 0
    evidence_found = 0
    skipped_non_document_cases = []
    failures = []
    evidence_failures = []
    latencies_ms = []
    logger = logging.getLogger("app.rag.retriever")
    previous_level = logger.level
    logger.setLevel(logging.CRITICAL)
    try:
        # Exercise the app's current retriever, forcing its normal lexical
        # fallback so this run cannot contact an embedding provider.
        with patch("app.rag.retriever.embed_query", side_effect=RuntimeError("offline evaluation")):
            for case in cases:
                expected = [name for name in case.get("expected_sources", []) if name in loaded_sources]
                if not expected:
                    skipped_non_document_cases.append(case["id"])
                    continue
                started = time.perf_counter()
                results = retrieve(case["query"], db, business_id=business_id, top_k=5)
                latencies_ms.append((time.perf_counter() - started) * 1000)
                found_sources = {result.filename for result in results}
                found_contents = fold_topic_text("\n".join(result.content for result in results))
                case_hits = sum(source in found_sources for source in expected)
                total_expected_sources += len(expected)
                source_hits += case_hits
                evaluated_cases += 1
                complete_cases += case_hits == len(expected)
                evidence = [term for term in case.get("must_include", [])
                            if fold_topic_text(term) in found_contents]
                evidence_requirements += len(case.get("must_include", []))
                evidence_found += len(evidence)
                missing_evidence = [term for term in case.get("must_include", [])
                                    if fold_topic_text(term) not in found_contents]
                if missing_evidence:
                    evidence_failures.append({
                        "id": case["id"],
                        "missing_evidence_terms": missing_evidence,
                        "retrieved_chunks": [
                            {
                                "source": result.filename,
                                "chunk_index": result.chunk_index,
                                "similarity": round(result.similarity, 4),
                                "preview": result.content[:240],
                            }
                            for result in results
                        ],
                    })
                if case_hits != len(expected):
                    failures.append({
                        "id": case["id"],
                        "expected_sources": expected,
                        "retrieved_sources": sorted(source for source in found_sources if source),
                        "missing_sources": [source for source in expected if source not in found_sources],
                        "retrieved_chunk_count": len(results),
                    })
    finally:
        logger.setLevel(previous_level)
        db.close()
        engine.dispose()
    return {
        "mode": "current_app_retriever_lexical_fallback_only",
        "vector_embeddings": "disabled; no provider calls",
        "llm_answer_generation": "not_run; no provider calls",
        "loaded_sources": loaded_sources,
        "source_chunk_count": chunk_total,
        "cases_with_known_document_sources": evaluated_cases,
        "cases_skipped_because_source_is_structured_or_not_in_demo_pack": skipped_non_document_cases,
        "expected_source_recall_at_5": round(source_hits / max(total_expected_sources, 1), 4),
        "all_expected_document_sources_in_top_5_rate": round(complete_cases / max(evaluated_cases, 1), 4),
        "answer_contract_context_overlap_rate": round(evidence_found / max(evidence_requirements, 1), 4),
        "answer_contract_context_overlap_diagnostics": evidence_failures,
        "answer_contract_context_overlap_note": (
            "Diagnostic only: must_include defines generated-answer expectations and may be paraphrased; "
            "it is not a retrieval metric or a semantic proof of grounding."
        ),
        "mean_retrieval_latency_ms": round(sum(latencies_ms) / max(len(latencies_ms), 1), 2),
        "failures": failures,
    }


def main() -> int:
    # PowerShell may expose a legacy code page even though the report is UTF-8.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.WARNING)
    case_path = ROOT / "knowledge_base" / "demo-rag-evaluation.vi-en.jsonl"
    route_path = ROOT / "docs" / "chatbot-evaluation-set.jsonl"
    answer_key_path = ROOT / "docs" / "chatbot-evaluation-answer-key.jsonl"
    report_path = ROOT / "docs" / "rag-evaluation-latest-report.json"
    cases_100 = load_cases(route_path)
    cases_demo = load_cases(case_path)
    if len(cases_100) != 100 or len(cases_demo) != 40:
        raise ValueError(f"Expected 100 routing cases and 40 demo RAG cases; got {len(cases_100)} and {len(cases_demo)}")
    if not answer_key_path.exists():
        write_answer_key(cases_100, answer_key_path)
    route_failures = [
        {"id": case["id"], "expected": case["expected_action"], "actual": expected_route(case["user"])}
        for case in cases_100
        if expected_route(case["user"]) != case["expected_action"]
    ]
    retrieval = evaluate_demo_retrieval(cases_demo)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "summary": "Retrieval and route checks only; LLM answer generation was not called.",
        "routing_100": {
            "total": len(cases_100),
            "passed": len(cases_100) - len(route_failures),
            "accuracy": round((len(cases_100) - len(route_failures)) / len(cases_100), 4),
            "failures": route_failures,
            "note": "This checks the deterministic route classifier, not end-to-end CRM/order database results.",
        },
        "demo_rag_retrieval_40": retrieval,
        "answer_generation": {
            "status": "not_run",
            "reason": "A real LLM call can consume the shop's configured AI quota; this run keeps evaluation local and cost-free.",
            "answer_contracts": str(answer_key_path),
        },
        "interpretation": {
            "retrieval_error": "Expected source missing from top five retrieved chunks.",
            "answer_error": "Must-include/must-not-include, citation validity, and factual answer quality require an actual generated answer; not inferred from retrieval metrics.",
            "tenant_data": "No live shop database or customer records were read.",
        },
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nSaved report: {report_path}")
    print(f"Saved 100-case answer/source key: {answer_key_path}")
    return 1 if route_failures or retrieval["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
