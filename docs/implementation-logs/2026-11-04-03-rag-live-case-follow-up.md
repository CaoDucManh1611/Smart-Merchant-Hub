# RAG live-case follow-up fixes

Date: 2026-11-04  
Branch: `codex/rag-rfm-all-updates-20261104`

## Findings addressed

| Case | Change |
| --- | --- |
| 23 | Budget browse still returns the ten lowest-priced matches, and now says how many matched and that the displayed ten are only the first results when more exist. |
| 25 | “I want to buy…” no longer counts as an order action by itself. A question asking price/stock/total stays on the read-only catalog path and calculates both mirror prices and stock. |
| 26 | Multi-item totals group results by requested product type. The bot shows matching names, current prices and stock before asking for vehicle details; it calculates a total only when each requested type resolves to one in-stock item. |
| 27 and 33 | Customer-facing response paths redact catalog SKU codes while preserving product specifications such as tire sizes and manufacturer model numbers. |
| 43 | An incomplete code prefix is recognized before generic retrieval; the reply explicitly calls it incomplete and can identify the matching product without exposing the internal code. |
| 47 | A service price question returns its catalog price/unit/duration without an unsolicited appointment-availability question. An explicit availability check with no date asks for the missing date/time. |
| 50 | Existing vehicle-specific product matching returns facts for the named model and keeps a compatibility caveat when the catalog cannot guarantee fitment. |

## Code and regression coverage

- `backend/app/services/auto_reply_service.py`
- `backend/app/services/conversation_graph.py`
- `backend/tests/test_chatbot_answer_routing.py`
- `backend/tests/test_conversation_graph.py`

## Verification

- `python -m pytest tests/test_chatbot_answer_routing.py tests/test_conversation_graph.py -q`: **93 passed**.
- `git diff --check`: passed.
- No new Telegram message was sent and no live server/worker was restarted in this step. The changes are verified against local tests; the running bot must reload this checkout before a live response can confirm deployment behavior.
- No commit or push was made.
