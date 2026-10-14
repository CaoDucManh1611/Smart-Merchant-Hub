"""Run the deterministic RAG routing regression set without calling an LLM.

This is a fast pre-deploy check.  It validates that representative questions
reach the expected product, policy, order, clarification, or handoff route.
The live LLM answer quality is still measured with response feedback.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.chatbot_router import classify_intent as expected_route


def main() -> int:
    path = ROOT / "docs" / "chatbot-evaluation-set.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    failures = []
    for row in rows:
        actual = expected_route(row["user"])
        if actual != row["expected_action"]:
            failures.append({"id": row["id"], "expected": row["expected_action"], "actual": actual})
    print(json.dumps({"total": len(rows), "passed": len(rows) - len(failures), "failed": failures}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
