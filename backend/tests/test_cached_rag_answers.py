import importlib.util
import json
from pathlib import Path
import sys


def test_cached_evaluation_checks_sources_and_verifies_privacy_in_an_isolated_fixture(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[2] / "scripts" / "evaluate_cached_rag_answers.py"
    spec = importlib.util.spec_from_file_location("cached_rag_evaluation", path)
    evaluator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evaluator)
    input_path, output_path = tmp_path / "vector.json", tmp_path / "result.json"
    cases = [
        {"id": "verified", "query": "SKU-A1 giá bao nhiêu?", "retrieved_contents": ["SKU-A1 giá 10000 VND."],
         "must_include": ["sku-a1", "10.000 VND"], "must_not_include": ["miễn phí"]},
        {"id": "invented", "query": "Phí giao hàng?", "retrieved_contents": ["Phí giao hàng: 30000 VND."]},
        {"id": "privacy", "query": "Please don't remember that I like pink.", "retrieved_contents": ["Preferences policy"]},
    ]
    for case in cases:
        case.update(retrieved_chunk_ids=[1], retrieved_sources=["synthetic.md"])
    input_path.write_text(json.dumps({"retrieval": {"fully_hybrid_cases": 3}, "cases": cases}), encoding="utf-8")
    outputs = iter(["SKU-A1 giá 10000 VND [Nguồn 1]", "Phí giao hàng 10000 VND [Nguồn 1]"])
    calls = []

    def fake_llm(messages):
        calls.append(messages)
        return next(outputs)

    monkeypatch.setattr(evaluator, "call_llm", fake_llm)
    monkeypatch.setattr(sys, "argv", ["eval", "--report", str(input_path), "--output", str(output_path)])
    evaluator.main()
    result = json.loads(output_path.read_text(encoding="utf-8"))
    assert len(calls) == 2
    assert result["answers"]["citation_passed"] == 1
    assert result["answers"]["verified_crm_actions"] == 1
    assert result["answers"]["handoff_cases"] == 1
    assert "10000" not in result["cases"][1]["served_answer"]
    assert result["cases"][2]["answer_method"] == "isolated_crm_privacy_action"
    assert result["cases"][2]["citation_required"] is False
    assert result["answers"]["must_include_terms_checked"] == 2
    assert result["cases"][0]["must_include_missing"] == ["10.000 VND"]
    assert result["cases"][0]["literal_evidence_passed"] is False
    assert result["answers"]["must_not_include_violations"] == 0


def test_cached_evidence_checks_accept_unicode_dashes_and_accents():
    import importlib.util

    path = Path(__file__).resolve().parents[2] / "scripts" / "evaluate_cached_rag_answers.py"
    spec = importlib.util.spec_from_file_location("cached_rag_evaluation_terms", path)
    evaluator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evaluator)
    case = {"must_include": ["DM-APP-001", "màu hồng"], "must_not_include": ["đã giao"]}
    assert evaluator._evidence_checks(case, "DM‑APP‑001 có màu hồng") == ([], [])
    assert evaluator._evidence_checks(case, "DM‑APP‑001 đã giao") == (["màu hồng"], ["đã giao"])


def test_cached_evaluation_restores_forbidden_terms_from_original_contract(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[2] / "scripts" / "evaluate_cached_rag_answers.py"
    spec = importlib.util.spec_from_file_location("cached_contract_restore", path)
    evaluator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evaluator)
    input_path, cases_path, output_path = tmp_path / "report.json", tmp_path / "cases.jsonl", tmp_path / "out.json"
    input_path.write_text(json.dumps({"retrieval": {"fully_hybrid_cases": 1}, "cases": [{
        "id": "policy", "query": "Phí giao hàng?", "retrieved_contents": ["Phí giao hàng 30000 VND."],
        "retrieved_chunk_ids": [1], "retrieved_sources": ["policy.md"],
    }]}), encoding="utf-8")
    cases_path.write_text(json.dumps({"id": "policy", "must_not_include": ["đã thanh toán"]}), encoding="utf-8")
    monkeypatch.setattr(evaluator, "call_llm", lambda _messages: "Phí giao hàng 30000 VND, đã thanh toán [Nguồn 1]")
    # The citation gate would reject a payment claim without payment evidence.
    # This test isolates contract restoration from that independent gate.
    monkeypatch.setattr(evaluator, "has_valid_citations", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(sys, "argv", ["eval", "--report", str(input_path), "--cases", str(cases_path), "--output", str(output_path)])
    evaluator.main()
    result = json.loads(output_path.read_text(encoding="utf-8"))
    assert result["answers"]["must_not_include_violations"] == 1
    assert result["cases"][0]["must_not_include_found"] == ["đã thanh toán"]
