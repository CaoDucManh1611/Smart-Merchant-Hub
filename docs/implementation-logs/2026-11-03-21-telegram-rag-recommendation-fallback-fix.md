# Telegram RAG recommendation fallback fix

## Symptom

Telegram returned the generic insufficient-evidence reply for an explicit Wave Alpha 110 chain-and-sprocket question asking for an in-stock item under 500,000 VND.

## Evidence

- Conversation turn: `business_id=7`, `conversation_id=7`, incoming message `5036`, correlation `chatbot-turn:7:7:5036`.
- The persisted recommendation request ranked product `41` first: `XM-NSD-WA110`, “Bộ nhông sên dĩa dòng Wave Alpha 110”, current price 465,000 VND, available quantity 9, and compliant catalog checks.
- Retrieval diagnostics recorded zero BM25/vector chunks, but recommendation serving returned the eligible catalog candidate; lexical zero was not the reason the answer was missing.
- The graph appended recommendations and then treated the recommendation tool as a catalog tool. When both were selected, it also processed catalog separately, duplicating the full catalog evidence (up to 100 products and 100 services with descriptions).
- The correlated LLM call failed with Groq HTTP `413 Payload Too Large`; the graph retried and eventually returned its generic fallback.

## Changes

- Process recommendation retrieval before catalog evidence and de-duplicate tools.
- For recommendation turns, include only the top three allowlisted ranking fields and the matching current catalog rows; exclude feature snapshots and customer memory from the answer prompt.
- For recommendation-only product questions, build the reply from the current active catalog row, rechecking live price, stock, quality flags, and any explicit budget. This avoids an unnecessary answer-generation call for exact product facts.
- Keep mixed knowledge questions on the normal grounded LLM path.
- Record executed tools and safe candidate/catalog counts in the RAG run log.

## Verification

- Python syntax compilation and `git diff --check` run after the edit.
- Worker container restarted and health checked so the mounted graph code is loaded.
- No Telegram message was sent as part of verification; the earlier authorization covered only one test message. A live end-to-end reply remains unverified until the user sends the next message to the bot.

## Limits

This fix addresses recommendation turns that already return a current eligible product. It does not claim to fix zero-result retrieval for knowledge-only questions or validate the external Telegram delivery path.

## Follow-up after the user's two repeated messages

The first code change did not cover these two turns because the planner chose only `catalog`, so the recommendation-specific path did not run. Their RAG logs show `tools=["catalog"]`, 24 catalog entries, and a Groq `429 Too Many Requests` during answer generation. Added a deterministic planner bypass for clear product-recommendation wording (for example “cần thay”, “phù hợp”, and product context). It selects `recommendations + catalog`, after which the live-catalog reply path avoids a second LLM call. The follow-up passed syntax and diff checks; live Telegram confirmation is recorded below.

## Live confirmation

The user retried the same question after the follow-up was loaded. Worker log records incoming message `5042` as sent on Telegram. Its RAG run used `tools=["recommendations","catalog"]`, `recommendation_reply_mode="live_catalog_template"`, 3 ranked candidates, 5 current catalog evidence rows, and a graph duration of 91.14 ms. The visible answer matched the current first-ranked product: `XM-NSD-WA110`, 465,000 VND, 9 available. The full worker turn was 4,983.9 ms, including a 3,617.4 ms queue wait and 883.3 ms delivery; the RAG graph itself was 91.14 ms.
