"""Evaluate provider-neutral RAG predictions against the 100-case set."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.rag.evaluation import evaluate_predictions


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("predictions", type=Path, help="JSONL predictions exported by a RAG run")
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "docs" / "chatbot-evaluation-set.jsonl",
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--min-action-accuracy", type=float, default=0.8)
    parser.add_argument("--min-recall", type=float, default=0.8)
    parser.add_argument("--min-citation-pass-rate", type=float)
    parser.add_argument("--min-handoff-recall", type=float)
    parser.add_argument("--min-answer-contract-pass-rate", type=float)
    args = parser.parse_args()
    metrics = evaluate_predictions(_read_jsonl(args.cases), _read_jsonl(args.predictions), top_k=args.top_k)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    failed = (
        metrics["action_accuracy"] < args.min_action_accuracy
        or metrics["retrieval_recall_at_k"] < args.min_recall
        or args.min_citation_pass_rate is not None and metrics["citation_pass_rate"] < args.min_citation_pass_rate
        or args.min_handoff_recall is not None and metrics["handoff_recall"] < args.min_handoff_recall
        or args.min_answer_contract_pass_rate is not None
        and metrics["answer_contract_pass_rate"] < args.min_answer_contract_pass_rate
    )
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
