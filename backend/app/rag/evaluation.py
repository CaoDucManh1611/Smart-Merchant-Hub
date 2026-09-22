"""Deterministic metrics for the versioned RAG evaluation set."""

from __future__ import annotations

from typing import Any, Iterable


def _fold(value: object) -> str:
    return str(value or "").casefold()


def evaluate_predictions(
    cases: Iterable[dict[str, Any]],
    predictions: Iterable[dict[str, Any]],
    *,
    top_k: int = 5,
) -> dict[str, float | int]:
    """Score action routing, retrieval ranking and unsupported answer text.

    Predictions are deliberately provider-neutral JSON objects. Each object
    contains ``id``, ``action``, ``retrieved_contents`` and ``answer`` so the
    same 80-case set can evaluate a local run, Colab model, or production API.
    """
    case_list = list(cases)
    by_id = {str(row.get("id")): row for row in predictions}
    if not case_list:
        return {
            "case_count": 0,
            "action_accuracy": 0.0,
            "retrieval_recall_at_k": 0.0,
            "mrr": 0.0,
            "grounded_rate": 0.0,
        }

    action_hits = 0
    retrieval_hits = 0
    reciprocal_rank = 0.0
    retrieval_cases = 0
    grounded_hits = 0
    for case in case_list:
        prediction = by_id.get(str(case.get("id")), {})
        if str(prediction.get("action") or "") == str(case.get("expected_action") or ""):
            action_hits += 1

        answer = _fold(prediction.get("answer"))
        forbidden = [_fold(value) for value in case.get("must_not_include", []) if _fold(value)]
        if not any(value in answer for value in forbidden):
            grounded_hits += 1

        expected_terms = [_fold(value) for value in case.get("expected_retrieval_terms", []) if _fold(value)]
        if not expected_terms:
            continue
        retrieval_cases += 1
        contents = [_fold(value) for value in list(prediction.get("retrieved_contents") or [])[:max(1, top_k)]]
        rank = next(
            (
                index
                for index, content in enumerate(contents, start=1)
                if any(term in content for term in expected_terms)
            ),
            None,
        )
        if rank is not None:
            retrieval_hits += 1
            reciprocal_rank += 1.0 / rank

    total = len(case_list)
    denominator = max(1, retrieval_cases)
    return {
        "case_count": total,
        "action_accuracy": round(action_hits / total, 6),
        "retrieval_recall_at_k": round(retrieval_hits / denominator, 6),
        "mrr": round(reciprocal_rank / denominator, 6),
        "grounded_rate": round(grounded_hits / total, 6),
    }
