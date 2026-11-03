# RAG clarification-first behavior and label review v2 — 2026-11-03

## Changes

- Added a tenant-scoped ambiguity check for active catalog identities. When one short product name matches multiple SKUs, the bot asks the customer to select the exact item before returning its price, stock, or sale status.
- Exact full names and SKUs continue to resolve directly. Explicit color/size tokens narrow the ambiguity set; multi-word colors are normalized to their component tokens. If a required variant is still not unique, the bot asks which variant the customer means.
- Follow-up questions can reuse the customer's prior explicit product selection from inbound messages in the same conversation. The current message is skipped, and a nearer ambiguous product mention prevents falling back to an older selection.
- Numbered rental-room lookups (including “phòng trọ số 5”) and general room-availability questions (including “phòng trọ còn trống không” and “phòng nào còn trống không”) keep their existing catalog routes.
- Strengthened tests to verify clarification appears before product facts, variant ambiguity, selected-product follow-ups, rental routing, and tenant/status filters in the catalog query.

## Secondary AI label review

GPT-6 Sol (low reasoning) reviewed the same 34 frozen local A/B/C answer cases under the user-approved clarification-first rule for the four ambiguous “Serum” cases.

| Arm | Correct | Partial | Incorrect | Hard errors |
|---|---:|---:|---:|---:|
| A — RAG without live catalog | 13 | 20 | 1 | 1 |
| B — RAG + catalog | 28 | 6 | 0 | 0 |
| C — RAG + catalog + controller | 28 | 6 | 0 | 0 |

- AI review status: 34/34 `ai_approved` in the separate derived worksheet.
- Human review status: 34/34 canonical rows remain `pending`; no human reviewer or approval timestamps were filled.
- Controller retry: 0/34 in the frozen C arm, so this run provides no evidence of controller benefit.
- These are AI review labels against local development snapshots, not human ground truth or production measurements.

## Artifacts and verification

- AI review worksheet: `backend/.local-evaluation/rag-answer-eval-20261102-v2/rag-answer-ai-review-gpt6-sol-v2.csv`
- AI review summary: `backend/.local-evaluation/rag-answer-eval-20261102-v2/README-ai-review-gpt6-sol-v2.md`
- Focused tests: in PowerShell, set `$env:RUN_POSTGRES_TESTS='0'`, then run `python -m pytest tests/test_chatbot_answer_routing.py tests/test_product_resolver.py tests/test_agentic_rag_controller.py -q` — **61 passed**.
- No migrations, customer-facing model settings, commits, or pushes were performed.
