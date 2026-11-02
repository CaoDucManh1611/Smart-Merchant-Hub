# Gemini paired answer evaluation and harness fixes — 2026-11-02

## Work completed

- Ran A/B/C against the same 34-case set and frozen catalog/retrieval snapshots using `gemini-3.5-flash-lite`. All 34 cases completed for each arm; no customer messages were sent.
- Added exact-prompt pairing to `backend/scripts/prepare_rag_snapshot_eval.py`. When two arms have byte-for-byte equal messages and generation configuration, the later arm reuses the earlier answer and records the pairing. This removes provider sampling noise from arm comparisons and avoids duplicate API calls on future runs. Legacy outputs are normalized while preserving differing raw answers for audit.
- Added controller diagnostics for retry candidates, prompt changes, and identical-prompt reuse.
- Fixed the automatic fact checker to ignore numeric citation IDs. A prior flag treating `[Nguồn 1]` as available stock was a false positive; results below use the corrected checker.
- Added optional Gemini usage metadata to `call_gemini` in `backend/app/rag/llm_caller.py`. Existing call sites still return plain text by default; the evaluation harness can request token counts. The generic configured cost estimate is marked as a proxy and must be reconciled with provider billing.
- Added regression coverage for exact-prompt reuse and Gemini token metadata.

## Evaluation

The frozen set contains 34 cases across shops 1 (11), 4 (12), and 7 (11): availability 3, catalog plus policy 2, clarification 3, policy 2, price 9, exact SKU 3, stock 9, and unknown SKU 3.

| Arm | Completed | Explicit price/stock mismatches | p50 / p95 end-to-end |
|---|---:|---:|---:|
| A — no live catalog fact | 34/34 | 4 | 18.87 s / 27.28 s |
| B — current catalog | 34/34 | 0 | 3.03 ms / 27.28 s |
| C — catalog + controller, paired | 34/34 | 0 | 3.03 ms / 27.28 s |

The latency mix differs by route: B/C had 27 deterministic catalog responses (p50 2.76 ms, p95 6.08 ms) and 7 generated responses (p50 22.27 s, p95 39.26 s). A used generated responses on all 34 cases (p50 18.87 s, p95 27.28 s). These are local development measurements, not production SLOs.

The raw C output had one numeric mismatch, but the case used the same B/C prompt and evidence, and the controller made no retry on any case. The derived paired report reuses an earlier identical-prompt arm and preserves the raw C answer. Thus this mismatch is model-generation variation, not evidence that the controller changed the result. No controller benefit was measured: 0/34 retry candidates and 0/34 B-to-C prompt changes. The run does not justify activating the controller.

The four A mismatches were stale product facts from retrieved knowledge text, while B used current structured catalog facts. A fifth initial flag was cleared because it came from citation `[Nguồn 1]`, not a stock claim. This is a narrow automatic consistency check, not an evaluation of semantic correctness. Every case remains pending human review. Citation IDs were in range, but entailment was not scored.

## Token and cost accounting

The completed run predates usage-metadata support, so token totals and billed cost are unavailable and are not backfilled. Gemini token accounting is now test-covered for subsequent runs. `AI_COST_PER_1K_TOKENS` is generic; any resulting estimate must be checked against the provider's actual model rate and billing data.

## Verification

- `test_gemini_sdk.py`, `test_rag_snapshot_eval_pairing.py`, `test_agentic_rag_controller.py`, and `test_agentic_rag_evaluation.py`: **9 passed** in the running backend container.
- `py_compile` passed for the updated evaluator and Gemini caller.
- Runtime observation: agentic mode `off`; retrieval mode `bm25`.
- No migration, training, production traffic, commit, or push was performed.

## Review artifact

- Human review guide: `backend/.local-evaluation/rag-answer-eval-20261102-v2/README-human-review-gemini-paired-v1.md`
- Reviewer CSV: `backend/.local-evaluation/rag-answer-eval-20261102-v2/rag-answer-human-review-gemini-paired-v1.csv`
- Raw answer run: `backend/.local-evaluation/rag-answer-eval-20261102-v2/answer-abcs-gemini-v1.json`
- Paired report: `backend/.local-evaluation/rag-answer-eval-20261102-v2/answer-abcs-gemini-paired-v1.json`

## Remaining gate

Human-review the 34 cases before drawing answer-quality conclusions. After labels are approved, rerun the paired comparison on the same snapshots; separately add hard cases that trigger controller retries, since the current set produced no controller context change.
