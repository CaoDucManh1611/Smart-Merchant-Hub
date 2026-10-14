"""Run isolated routing checks and optionally score 100 per-turn predictions."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.rag.evaluation import evaluate_predictions  # noqa: E402
from app.services.chatbot_router import classify_intent  # noqa: E402


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, help="Optional independent-turn prediction JSONL")
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "docs" / "chatbot-evaluation-100-latest-report.json",
    )
    args = parser.parse_args()

    cases = read_jsonl(ROOT / "docs" / "chatbot-evaluation-set.jsonl")
    answer_key = {row["id"]: row for row in read_jsonl(ROOT / "docs" / "chatbot-evaluation-answer-key.jsonl")}
    if len(cases) != 100:
        parser.error(f"Expected exactly 100 cases, found {len(cases)}")

    routing = [
        {"id": case["id"], "expected": case["expected_action"], "actual": classify_intent(case["user"])}
        for case in cases
    ]
    route_failures = [row for row in routing if row["expected"] != row["actual"]]
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "case_count": len(cases),
        "isolation": "One input turn per case ID; no conversation history or previous answer is carried forward.",
        "routing": {
            "passed": len(cases) - len(route_failures),
            "accuracy": round((len(cases) - len(route_failures)) / len(cases), 4),
            "failures": route_failures,
        },
        "answer_quality": {"status": "not_run", "reason": "Pass --predictions to score answers, citations, handoff and latency."},
    }

    if args.predictions:
        prediction_rows = read_jsonl(args.predictions)
        missing_keys = sorted({str(row.get("id")) for row in prediction_rows} - set(answer_key))
        if missing_keys:
            parser.error("Prediction IDs are not in the answer key: " + ", ".join(missing_keys))
        score_cases = []
        for case in cases:
            score_cases.append({**case, **answer_key.get(case["id"], {})})
        report["answer_quality"] = {
            "status": "scored",
            "prediction_file": str(args.predictions.resolve()),
            "metrics": evaluate_predictions(score_cases, prediction_rows),
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Saved report: {args.output}")
    return 1 if route_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
