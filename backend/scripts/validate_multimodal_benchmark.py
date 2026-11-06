"""Validate the frozen multimodal benchmark contract without running providers."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def validate_manifest(payload: dict) -> dict:
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("cases_required")
    groups = [case.get("group") for case in cases]
    if len(set(groups)) != 15 or any(not group for group in groups):
        raise ValueError("exactly_15_named_groups_required")
    case_ids = [case.get("case_id") for case in cases]
    if len(set(case_ids)) != len(case_ids) or any(not case_id for case_id in case_ids):
        raise ValueError("unique_case_ids_required")
    thresholds = payload.get("acceptance_thresholds_locked_before_run")
    if not isinstance(thresholds, dict) or len(thresholds) != 11:
        raise ValueError("locked_acceptance_thresholds_required")
    if payload.get("feature_flag_required") != "RAG_IMAGE_CATALOG_MATCH_ENABLED":
        raise ValueError("vision_flag_contract_required")

    runtime = payload.get("runtime_fields_required_per_case") or []
    review = payload.get("human_review_fields_required_per_case") or []
    missing_runtime = sum(any(case.get(field) in (None, "", []) for field in runtime) for case in cases)
    missing_review = sum(any(case.get(field) in (None, "", []) for field in review) for case in cases)
    minimum = int(payload.get("minimum_cases_per_group") or 0)
    counts = Counter(groups)
    ready = (
        minimum > 0
        and all(count >= minimum for count in counts.values())
        and missing_runtime == 0
        and missing_review == 0
    )
    return {
        "benchmark_id": payload.get("benchmark_id"),
        "contract_valid": True,
        "acceptance_status": "READY_FOR_GATE" if ready else "NOT_READY",
        "group_count": len(counts),
        "case_count": len(cases),
        "minimum_cases_per_group": minimum,
        "cases_missing_runtime_evidence": missing_runtime,
        "cases_missing_human_review": missing_review,
        "quality_pass": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    result = validate_manifest(json.loads(args.manifest.read_text(encoding="utf-8")))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
