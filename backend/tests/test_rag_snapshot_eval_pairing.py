from scripts.prepare_rag_snapshot_eval import (
    _automatic_fact_checks,
    _find_reusable_answer,
    _pair_identical_arm_outputs,
)


def test_reuses_only_an_earlier_arm_with_identical_prompt_and_config():
    messages = [{"role": "user", "content": "question"}]
    config = {"provider": "gemini", "model": "test", "temperature": 0.1}
    arms = {
        "A_no_catalog": {
            "answer": "A", "messages": messages, "generation_config": config,
        },
        "B_catalog": {
            "answer": "B", "messages": [{"role": "user", "content": "different"}],
            "generation_config": config,
        },
    }

    assert _find_reusable_answer(arms, ["A_no_catalog"], messages, config) == (
        "A_no_catalog", arms["A_no_catalog"]
    )
    assert _find_reusable_answer(arms, ["B_catalog"], messages, config) is None
    assert _find_reusable_answer(
        arms, ["A_no_catalog"], messages, {**config, "temperature": 0.2}
    ) is None


def test_pairs_legacy_outputs_and_keeps_the_unpaired_answer_for_audit():
    messages = [{"role": "user", "content": "question"}]
    config = {"provider": "gemini", "model": "test", "temperature": 0.1}
    arms = {
        "A_no_catalog": {
            "answer": "paired answer [Nguồn 1]", "messages": messages,
            "generation_config": config, "usage": {"latency_ms": 15},
            "generation_latency_ms": 15, "evidence": [{}],
        },
        "B_catalog": {
            "answer": "unpaired output", "messages": messages,
            "generation_config": config, "usage": {"latency_ms": 28},
            "generation_latency_ms": 28, "retrieval_latency_ms": 2,
            "controller_retry_latency_ms": 3, "end_to_end_latency_ms": 33,
            "evidence": [{}], "automatic_checks": {},
        },
    }

    _pair_identical_arm_outputs({"arms": arms, "expected_facts": {}}, ("A_no_catalog", "B_catalog"))

    result = arms["B_catalog"]
    assert result["answer"] == "paired answer [Nguồn 1]"
    assert result["unpaired_answer"] == "unpaired output"
    assert result["answer_generation_reused_from"] == "A_no_catalog"
    assert result["usage"]["latency_ms"] == 15
    assert result["end_to_end_latency_ms"] == 20
    assert result["citation_references"] == [1]
    assert result["citation_ids_in_range"] is True


def test_stock_checker_does_not_read_citation_number_as_quantity():
    checks = _automatic_fact_checks(
        {"expected_facts": {"available_quantity": 44}},
        "Chưa có thông tin cụ thể về số lượng tồn kho [Nguồn 1].",
    )

    assert checks["stock_match"] is None
    assert checks["wrong_price_or_stock"] is not True
