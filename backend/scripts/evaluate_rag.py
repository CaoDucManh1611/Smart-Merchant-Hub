"""Evaluate provider-neutral RAG prediction JSONL against the 80-case set."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

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
    args = parser.parse_args()
    metrics = evaluate_predictions(_read_jsonl(args.cases), _read_jsonl(args.predictions), top_k=args.top_k)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    if metrics["action_accuracy"] < args.min_action_accuracy or metrics["retrieval_recall_at_k"] < args.min_recall:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
