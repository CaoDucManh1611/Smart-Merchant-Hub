import json
from pathlib import Path

from scripts.validate_multimodal_benchmark import validate_manifest


MANIFEST = Path(__file__).parents[1] / "test_data" / "rag_multimodal_benchmark_v1.json"


def test_multimodal_manifest_has_15_groups_and_locked_thresholds():
    result = validate_manifest(json.loads(MANIFEST.read_text(encoding="utf-8")))
    assert result["contract_valid"] is True
    assert result["group_count"] == 15
    assert result["quality_pass"] is None


def test_multimodal_manifest_fails_closed_until_runtime_and_human_evidence_exist():
    result = validate_manifest(json.loads(MANIFEST.read_text(encoding="utf-8")))
    assert result["acceptance_status"] == "NOT_READY"
    assert result["cases_missing_runtime_evidence"] == 15
    assert result["cases_missing_human_review"] == 15


def test_multimodal_manifest_rejects_missing_group():
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    payload["cases"].pop()
    try:
        validate_manifest(payload)
    except ValueError as error:
        assert str(error) == "exactly_15_named_groups_required"
    else:
        raise AssertionError("invalid manifest was accepted")
