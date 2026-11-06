# RAG similar-question routing fixes

Date: 2026-11-04
Branch: `codex/rag-rfm-all-updates-20261104`

## Changes

- Product and room listing replies now ask the customer to choose only when the catalog returned multiple options. One exact match is presented directly.
- A vehicle-specific multi-product question is allowed past the generic ambiguity guard. Candidate products are narrowed by the named vehicle and structured fitment fields before facts are returned; the reply still avoids guaranteeing fit without enough evidence.
- Comparison follow-ups such as “loại rẻ hơn còn bao nhiêu?” bypass broad comparison/discovery routes and resolve against the prior comparison in the current conversation.
- Generic spark-plug fit questions continue to ask for the vehicle before selecting a model.
- Intent words in the “carry hot water” use case no longer become a false product identity constraint; the verified thermos remains eligible under the user's budget.
- Customer-facing single-item recommendations no longer append a redundant “which one?” question.

## Verification

- `python -m pytest tests/test_chatbot_answer_routing.py -q`: **62 passed**.
- Restarted Docker Compose `backend` and `worker`; both are running, and the backend health check returned `healthy`.
- No message was sent to Telegram in this verification. The container restart loads the changes, but live channel replies still need to be observed on the next test message.
- No commit or push was made.
