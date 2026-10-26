"""Reproducible offline intent metrics for the CLO4 acceptance report."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from app.rag.prompt_builder import detect_reply_language  # noqa: E402
from app.services.chatbot_router import classify_intent  # noqa: E402
from evaluate_commerce_nlu_set import observed_intent  # noqa: E402


def classification_metrics(expected: list[str], actual: list[str]) -> dict:
    assert len(expected) == len(actual) and expected
    labels = sorted(set(expected) | set(actual))
    classes = {}
    for label in labels:
        tp = sum(truth == guess == label for truth, guess in zip(expected, actual))
        fp = sum(truth != label and guess == label for truth, guess in zip(expected, actual))
        fn = sum(truth == label and guess != label for truth, guess in zip(expected, actual))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        classes[label] = {
            "support": tp + fn,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(2 * precision * recall / (precision + recall), 4) if precision + recall else 0.0,
        }
    return {
        "cases": len(expected),
        "accuracy": round(sum(a == b for a, b in zip(expected, actual)) / len(expected), 4),
        "macro_f1": round(sum(row["f1"] for row in classes.values()) / len(classes), 4),
        "per_class": classes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    # Small self-check: one error among four examples gives 3/4 accuracy.
    assert classification_metrics(["a", "a", "b", "b"], ["a", "b", "b", "b"])["accuracy"] == 0.75

    router_cases = [json.loads(line) for line in (ROOT / "docs/chatbot-evaluation-set.jsonl").read_text(encoding="utf-8").splitlines() if line]
    commerce_cases = [row for row in json.loads((ROOT / "docs/commerce-nlu-evaluation-set.json").read_text(encoding="utf-8"))["cases"] if row["type"] == "utterance"]
    router_predictions = [classify_intent(row["user"]) for row in router_cases]
    commerce_predictions = [observed_intent(row["text"]) or "unhandled" for row in commerce_cases]
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": "Offline deterministic intent gates only; no LLM, live shop data, or external channel",
        "router_100": classification_metrics([row["expected_action"] for row in router_cases], router_predictions),
        "commerce_holdout": classification_metrics([row["expected_intent"] for row in commerce_cases], commerce_predictions),
        "commerce_language_accuracy": round(sum(detect_reply_language(row["text"]) == ("en" if row["reply_locale"].startswith("en") else "vi") for row in commerce_cases) / len(commerce_cases), 4),
        "failures": {
            "router": [{"id": row["id"], "expected": row["expected_action"], "actual": guess} for row, guess in zip(router_cases, router_predictions) if row["expected_action"] != guess],
            "commerce": [{"id": row["id"], "expected": row["expected_intent"], "actual": guess} for row, guess in zip(commerce_cases, commerce_predictions) if row["expected_intent"] != guess],
        },
        "rmse": {"status": "not_applicable", "reason": "These targets are categorical intents; numeric RMSE would not measure their correctness."},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"router_100": {k: v for k, v in report["router_100"].items() if k != "per_class"}, "commerce_holdout": {k: v for k, v in report["commerce_holdout"].items() if k != "per_class"}, "commerce_language_accuracy": report["commerce_language_accuracy"], "failures": report["failures"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
