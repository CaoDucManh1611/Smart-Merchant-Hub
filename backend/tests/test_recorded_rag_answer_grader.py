import json
from pathlib import Path

from scripts.grade_recorded_rag_answer_runs import grade_case, grade_files


CASES_PATH = Path(__file__).resolve().parents[1] / "test_data" / "rag_answer_quality_acceptance_v1.jsonl"
CASES = {
    row["case_id"]: row
    for row in (json.loads(line) for line in CASES_PATH.read_text(encoding="utf-8").splitlines() if line.strip())
}


def _result(answer="", **kwargs):
    return {"generated_response": answer, "selected_tools": ["catalog"], **kwargs}


def test_grader_passes_only_objective_current_price_and_stock_claims():
    graded = grade_case(CASES["answer-001-price-stock"], _result(
        "Áo mẫu Alpha giá 250.000 đồng, còn 7 sản phẩm.",
    ))

    assert graded["outcome"] == "PASS_AUTOMATED"
    assert not graded["missing_required_claims"]


def test_unknown_explicit_sku_fuzzy_suggestion_fails_automated_grading():
    graded = grade_case(CASES["answer-008-unknown-sku"], _result(
        "Tên này khớp DEMO-ALPHA hoặc DEMO-BETA, bạn muốn chọn mã nào?",
    ))

    assert graded["outcome"] == "FAIL_AUTOMATED"
    assert "unknown_exact_code_reported_not_found" in graded["missing_required_claims"]
    assert "unknown_sku_fuzzy_candidate_suggested_as_match" in graded["prohibited_claims_detected"]


def test_provider_and_database_errors_are_not_scored_as_hallucinations():
    provider = grade_case(CASES["answer-013-cross-tenant"], _result(error_type="ClientError"))
    infrastructure = grade_case(CASES["answer-002-budget"], _result(error_type="OperationalError"))

    assert provider["outcome"] == "PROVIDER_ERROR"
    assert infrastructure["outcome"] == "INFRASTRUCTURE_ERROR"
    assert "hallucination" not in provider
    assert "hallucination" not in infrastructure
    assert not provider["missing_required_claims"]
    assert all(check["status"] == "NOT_MEASURED" for check in provider["checks"])


def test_provider_circuit_open_is_provider_error_not_infrastructure_or_hallucination():
    graded = grade_case(CASES["answer-008-unknown-sku"], _result(error_type="ProviderCircuitOpen"))

    assert graded["outcome"] == "PROVIDER_ERROR"
    assert not graded["missing_required_claims"]
    assert not graded["prohibited_claims_detected"]
    assert all(check["status"] == "NOT_MEASURED" for check in graded["checks"])


def test_grader_preserves_observed_synthetic_evidence_provenance():
    graded = grade_case(CASES["answer-010-no-evidence"], _result(
        error_type="ProviderCircuitOpen",
        retrieved_evidence=[{
            "chunk_id": "chunk-10",
            "metadata": {"synthetic_evidence_id": "policy:available", "synthetic": True},
        }],
        execution_safety={"synthetic_context": True, "external_customer_channel_invoked": False},
    ))

    assert graded["retrieved_evidence_ids"] == ["policy:available"]
    assert graded["retrieved_evidence"][0]["chunk_id"] == "chunk-10"
    assert graded["execution_safety"]["synthetic_context"] is True


def test_grade_files_uses_neutral_post_run_artifacts_and_keeps_provider_errors(tmp_path):
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text(
        "\n".join(json.dumps(case, ensure_ascii=False) for case in CASES.values()) + "\n",
        encoding="utf-8",
    )
    run_path = tmp_path / "postfix-run.json"
    results = []
    for case in CASES.values():
        result = {"case_id": case["case_id"], "generated_response": "", "error_type": "ProviderCircuitOpen"}
        if case["case_id"] == "answer-010-no-evidence":
            result["retrieved_evidence"] = [{
                "chunk_id": "chunk-10",
                "metadata": {"synthetic_evidence_id": "policy:available", "synthetic": True},
            }]
        results.append(result)
    run_path.write_text(json.dumps({
        "dataset": "smh-rag-answer-quality-synthetic-v1",
        "synthetic_only": True,
        "phase": "postfix",
        "results": results,
        "run_budget": {
            "attempt_records": [{"outcome": "error"}, {"outcome": "success"}],
            "calls": 20,
            "attempts": 2,
            "elapsed_seconds": 1.25,
        },
    }), encoding="utf-8")

    output_dir = tmp_path / "graded"
    summary = grade_files(cases_path, [run_path], output_dir)

    assert summary["provider_run_status"] == "RUNS_SUPPLIED_AND_GRADED"
    assert "post_fix_provider_run" not in summary
    assert summary["per_run"][0]["phase"] == "postfix"
    assert summary["per_run"][0]["outcome_counts"]["PROVIDER_ERROR"] == len(CASES)
    assert summary["per_run"][0]["infrastructure_case_errors"] == 0
    assert set(summary["artifacts"]) == {
        "recorded-answer-review-traces-sanitized.jsonl",
        "recorded-answer-case-review.csv",
    }
    assert all("pre-five-fix" not in name for name in summary["artifacts"])
    trace_rows = [json.loads(line) for line in (output_dir / summary["artifacts"][0]).read_text(encoding="utf-8").splitlines()]
    policy_row = next(row for row in trace_rows if row["case_id"] == "answer-010-no-evidence")
    assert policy_row["retrieved_evidence_ids"] == ["policy:available"]


def test_policy_answer_missing_eligibility_condition_fails():
    graded = grade_case(CASES["answer-011-policy-grounded"], _result(
        "Bạn có thể đổi hàng trong 7 ngày kể từ khi nhận hàng.",
        selected_tools=["knowledge"],
    ))

    assert graded["outcome"] == "FAIL_AUTOMATED"
    assert "eligibility_condition" in graded["missing_required_claims"]


def test_unrequested_order_tool_selection_is_detected():
    graded = grade_case(CASES["answer-015-no-order-side-effect"], _result(
        "Tổng tạm tính 360.000 đồng, chưa tạo đơn.",
        selected_tools=["orders"],
    ))

    assert graded["outcome"] == "FAIL_AUTOMATED"
    assert "no_transaction_capability_selected" in graded["missing_required_claims"]
