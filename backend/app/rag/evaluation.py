"""Deterministic metrics for independent RAG evaluation cases."""

from __future__ import annotations

from math import ceil, log2
from typing import Any, Iterable

from app.rag.answer_guard import has_valid_citations
from app.rag.topics import fold_topic_text

_SOURCE_ALIASES = {
    "tenant_product_catalog": {"crm_product", "crm_catalog"},
    "tenant_product_catalog_or_approved_product_knowledge": {
        "crm_product", "crm_catalog", "demo-products.vi-en.csv", "approved_product_knowledge",
    },
    "authenticated_customer_order_record": {"crm_order"},
    "tenant_completed_sales_orders": {"crm_sales_rank", "crm_sales_summary"},
    "approved_tenant_delivery_policy": {"demo-support-policies.vi-en.md", "delivery_policy"},
    "approved_tenant_returns_warranty_policy": {"demo-support-policies.vi-en.md", "returns_policy"},
    "approved_tenant_payment_policy_or_verified_payment_record": {
        "demo-support-policies.vi-en.md", "crm_payment", "payment_policy",
    },
    "tenant_crm_customer_record": {"crm_customer"},
    "tenant_crm_deal_records": {"crm_lead", "crm_lead_query"},
    "tenant_customer_conversation_history": {"crm_message"},
    "tenant_customer_notes": {"crm_customer_note"},
}


def _fold(value: object) -> str:
    # Ignore accents, Unicode dash variants, narrow spaces, and Markdown
    # punctuation so formatting does not look like a factual error.
    return fold_topic_text(value)


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, ceil(len(ordered) * fraction) - 1))
    return round(ordered[index], 2)


def evaluate_product_rankings(cases: Iterable[dict], predictions: Iterable[dict], *, top_k: int = 5) -> dict:
    """Evaluate labeled product IDs, independently of wording and the LLM.

    Empty expected lists represent cases where no product should be suggested.
    Repeated IDs occupy ranking slots but cannot earn relevance twice.
    """
    by_id = {str(row.get("id")): row for row in predictions}
    results = []
    segment_cases = segment_hits = 0
    for case in cases:
        if "expected_product_ids" not in case:
            continue
        present = str(case.get("id")) in by_id
        prediction = by_id.get(str(case.get("id")), {})
        expected = {str(value) for value in case["expected_product_ids"]}
        actual = [str(value) for value in prediction.get("recommended_product_ids", [])][:max(1, top_k)]
        forbidden = {str(value) for value in case.get("forbidden_product_ids", [])}
        seen = set()
        gains = []
        for value in actual:
            gains.append(int(value in expected and value not in seen))
            seen.add(value)
        hits = sum(gains)
        ideal = sum(1 / log2(rank + 2) for rank in range(min(len(expected), max(1, top_k))))
        dcg = sum(gain / log2(rank + 2) for rank, gain in enumerate(gains))
        abstained = not actual
        results.append({
            "id": case.get("id"),
            "precision": hits / max(1, top_k) if expected else float(abstained and present),
            "recall": hits / len(expected) if expected else float(abstained and present),
            "ndcg": dcg / ideal if ideal else float(abstained and present),
            "reciprocal_rank": next((1 / (rank + 1) for rank, gain in enumerate(gains) if gain), 0.0),
            "forbidden_products": sorted(set(actual) & forbidden),
        })
        if "expected_rfm_segment" in case:
            segment_cases += 1
            segment_hits += prediction.get("rfm_segment") == case["expected_rfm_segment"]
    count = len(results)
    return {
        "case_count": count,
        "top_k": max(1, top_k),
        "precision_at_k": round(sum(row["precision"] for row in results) / max(1, count), 6),
        "recall_at_k": round(sum(row["recall"] for row in results) / max(1, count), 6),
        "ndcg_at_k": round(sum(row["ndcg"] for row in results) / max(1, count), 6),
        "mrr": round(sum(row["reciprocal_rank"] for row in results) / max(1, count), 6),
        "forbidden_product_rate": round(sum(bool(row["forbidden_products"]) for row in results) / max(1, count), 6),
        "rfm_segment_cases": segment_cases,
        "rfm_segment_accuracy": round(segment_hits / max(1, segment_cases), 6),
        "cases": results,
    }


def evaluate_predictions(
    cases: Iterable[dict[str, Any]],
    predictions: Iterable[dict[str, Any]],
    *,
    top_k: int = 5,
) -> dict[str, Any]:
    """Score routing, retrieval, answer contracts, citations, handoff and latency.

    A prediction is one isolated turn with ``id``, ``action``,
    ``retrieved_contents``, ``retrieved_sources``, ``answer``,
    ``handoff_required`` and optional ``latency_ms``/``provider_error``. The
    automatic answer checks are contract checks, not a substitute for human
    semantic review.
    """
    case_list = list(cases)
    by_id = {str(row.get("id")): row for row in predictions}
    if not case_list:
        return {"case_count": 0, "missing_prediction_count": 0}

    action_hits = answer_cases = answer_contract_cases = answer_contract_hits = forbidden_clean = 0
    retrieval_hits = retrieval_cases = 0
    reciprocal_rank = 0.0
    required_terms = found_terms = 0
    citation_cases = citation_hits = 0
    source_cases = source_hits = expected_source_count = 0
    handoff_tp = handoff_fp = handoff_fn = 0
    latencies: list[float] = []
    estimated_costs: list[float] = []
    provider_errors = 0
    case_results = []

    for case in case_list:
        prediction = by_id.get(str(case.get("id")))
        prediction = prediction or {}
        action_ok = str(prediction.get("action") or "") == str(case.get("expected_action") or "")
        action_hits += action_ok

        answer = str(prediction.get("answer") or "")
        answer_folded = _fold(answer)
        answer_present = bool(answer.strip())
        required = [_fold(value) for value in case.get("must_include", []) if _fold(value)]
        forbidden = [_fold(value) for value in case.get("must_not_include", []) if _fold(value)]
        required_found = [term for term in required if term in answer_folded]
        forbidden_found = [term for term in forbidden if term in answer_folded]
        if answer_present:
            answer_cases += 1
            required_terms += len(required)
            found_terms += len(required_found)
            forbidden_clean += not forbidden_found
            if required:
                answer_contract_cases += 1
                answer_contract_hits += len(required_found) == len(required)

        contents = [str(value) for value in list(prediction.get("retrieved_contents") or [])[:max(1, top_k)]]
        retrieval_required = case.get("retrieval_required", case.get("expected_action") == "search_knowledge")
        expected_terms = (
            [_fold(value) for value in case.get("expected_retrieval_terms", []) if _fold(value)]
            if retrieval_required else []
        )
        retrieval_rank = None
        if expected_terms:
            retrieval_cases += 1
            retrieval_rank = next(
                (index for index, content in enumerate(contents, start=1)
                 if any(term in _fold(content) for term in expected_terms)),
                None,
            )
            if retrieval_rank is not None:
                retrieval_hits += 1
                reciprocal_rank += 1.0 / retrieval_rank

        expected_sources = [str(value) for value in case.get("expected_sources", [])]
        actual_sources = {str(value) for value in prediction.get("retrieved_sources", [])}
        if expected_sources and prediction.get("retrieved_sources") is not None:
            source_cases += 1
            matched_sources = sum(
                source in actual_sources or bool(_SOURCE_ALIASES.get(source, set()) & actual_sources)
                for source in expected_sources
            )
            source_hits += matched_sources
            expected_source_count += len(expected_sources)

        citation_required = case.get("citation_required", case.get("expected_action") == "search_knowledge")
        citation_valid = prediction.get("citation_valid")
        if citation_valid is None and answer_present:
            citation_valid = has_valid_citations(answer, contents, query=case.get("query") or case.get("user"))
        if citation_required:
            citation_cases += 1
            citation_hits += bool(citation_valid)

        expected_handoff = bool(case.get("expected_handoff", case.get("expected_action") == "handoff"))
        actual_handoff = bool(prediction.get("handoff_required", False))
        handoff_tp += expected_handoff and actual_handoff
        handoff_fp += not expected_handoff and actual_handoff
        handoff_fn += expected_handoff and not actual_handoff

        latency = prediction.get("latency_ms")
        if isinstance(latency, (int, float)) and latency >= 0:
            latencies.append(float(latency))
        estimated_cost = prediction.get("estimated_ai_cost")
        if isinstance(estimated_cost, (int, float)) and estimated_cost >= 0:
            estimated_costs.append(float(estimated_cost))
        provider_errors += bool(prediction.get("provider_error"))
        case_results.append({
            "id": case.get("id"),
            "action_ok": bool(action_ok),
            "missing_required_terms": [term for term in required if term not in answer_folded],
            "forbidden_terms_found": forbidden_found,
            "retrieval_rank": retrieval_rank,
            "retrieval_required": bool(retrieval_required),
            "missing_sources": [
                source for source in expected_sources
                if source not in actual_sources and not (_SOURCE_ALIASES.get(source, set()) & actual_sources)
            ],
            "citation_required": bool(citation_required),
            "citation_valid": bool(citation_valid) if citation_valid is not None else None,
            "expected_handoff": expected_handoff,
            "actual_handoff": actual_handoff,
            "latency_ms": latency,
            "estimated_ai_cost": estimated_cost,
            "provider_error": bool(prediction.get("provider_error")),
        })

    total = len(case_list)
    return {
        "case_count": total,
        "missing_prediction_count": sum(str(case.get("id")) not in by_id for case in case_list),
        "action_accuracy": round(action_hits / total, 6),
        "retrieval_cases": retrieval_cases,
        "retrieval_recall_at_k": round(retrieval_hits / max(1, retrieval_cases), 6),
        "mrr": round(reciprocal_rank / max(1, retrieval_cases), 6),
        "answer_cases": answer_cases,
        "answer_contract_cases": answer_contract_cases,
        "must_include_term_rate": round(found_terms / max(1, required_terms), 6),
        "answer_contract_pass_rate": round(answer_contract_hits / max(1, answer_contract_cases), 6),
        "answer_accuracy_proxy": round(answer_contract_hits / max(1, answer_contract_cases), 6),
        "grounded_rate": round(forbidden_clean / max(1, answer_cases), 6),
        "source_cases": source_cases,
        "expected_source_count": expected_source_count,
        "expected_source_recall": round(source_hits / max(1, expected_source_count), 6),
        "citation_cases": citation_cases,
        "citation_pass_rate": round(citation_hits / max(1, citation_cases), 6),
        "handoff_precision": round(handoff_tp / max(1, handoff_tp + handoff_fp), 6),
        "handoff_recall": round(handoff_tp / max(1, handoff_tp + handoff_fn), 6),
        "service_error_rate": round(provider_errors / total, 6),
        "latency_cases": len(latencies),
        "latency_mean_ms": round(sum(latencies) / max(1, len(latencies)), 2),
        "latency_p50_ms": _percentile(latencies, 0.50),
        "latency_p95_ms": _percentile(latencies, 0.95),
        "estimated_cost_cases": len(estimated_costs),
        "estimated_ai_cost_total": round(sum(estimated_costs), 8),
        "estimated_ai_cost_mean": round(sum(estimated_costs) / max(1, len(estimated_costs)), 8),
        "estimated_ai_cost_unit": "configured quota cost units; not provider billing",
        "recommendation_metrics": evaluate_product_rankings(case_list, by_id.values(), top_k=top_k),
        "cases": case_results,
        "notes": [
            "Each prediction is scored by case ID; no prior conversation turns are included by this evaluator.",
            "Text contract checks and citation IDs are automatic proxies and do not prove semantic correctness.",
        ],
    }
