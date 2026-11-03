# RAG AI auto-adjudication and answer-safety follow-up — 2026-11-03

## Completed

- Produced a separate GPT-6 Sol AI-adjudicated copy for all 34 frozen cases. Its 34 rows are marked `ai_approved`, the reviewer explicitly identifies as AI, and generic correctness fields summarize arm B. Per-arm A/B/C labels remain in their dedicated columns.
- Preserved the original human-review worksheet and GPT-6 Sol v2 source worksheet. Neither is represented as human-approved.
- Fixed two answer-quality gaps identified in the AI review:
  - Return-policy retrieval no longer counts as warranty evidence. Combined return/warranty questions disclose when the shop source has no warranty terms.
  - Tire recommendations ask for tire size and front/rear position before listing candidates when either fitment field is missing.
- Added regression coverage and updated an existing channel test fixture for the ambiguity resolver.

## Frozen AI-reviewed results

| Arm | Correct | Partial | Incorrect | Hard errors |
|---|---:|---:|---:|---:|
| A | 13 | 20 | 1 | 1 |
| B | 28 | 6 | 0 | 0 |
| C | 28 | 6 | 0 | 0 |

All six B/C partial labels include four historical Serum answers, one combined returns/warranty answer, and one tire-fitment answer. The new serving code addresses the latter two. The frozen outputs have not yet been regenerated, so those counts remain historical and must not be reported as post-fix measurements. Controller retry remains 0/34.

## Verification

- `RUN_POSTGRES_TESTS=0 python -m pytest tests/test_chatbot_answer_routing.py tests/test_product_resolver.py tests/test_agentic_rag_controller.py -q` — **63 passed**.
- `RUN_POSTGRES_TESTS=0 python -m pytest tests/test_auto_reply_channels.py::test_product_attributes_use_same_current_crm_context_on_all_channels tests/test_chatbot_answer_routing.py -q` — **57 passed**.
- `git diff --check` — passed; only existing LF/CRLF notices were printed for the agentic controller and its test.
- A wider run that included all of `test_auto_reply_channels.py` reported 12 failures before refreshing its fixture: six parameterized cases omitted the new ambiguity-resolver mock, and six image-flow tests target a missing `app.services.conversation_graph` module. The six product-attribute cases now pass after the fixture update; the unrelated stale image-flow patch path was not changed.

## Limitations / next action

- The labels are AI judgments on local snapshots, not human ground truth or production measurements.
- Re-run the two fixed cases through the answer-generation harness to verify actual generated outputs before updating the measured B/C counts.
- The old C arm reused earlier answers in cases and had 0/34 controller retries; no controller benefit is established.
- No migrations, commits, or pushes were made.
