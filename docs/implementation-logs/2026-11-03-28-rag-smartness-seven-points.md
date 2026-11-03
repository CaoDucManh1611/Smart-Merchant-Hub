# RAG smartness pass: seven requested points

Date: 2026-11-03  
Branch: `codex/rag-improvements-20261102`  
Scope: improve retrieval and answer accuracy without adding per-message model calls or speculative industry branches.

## Result by requested point

| # | Result | Notes |
|---|---|---|
| 1. Structured intent router | Updated, scoped | `route_customer_message()` wraps the existing deterministic classifier and returns one structured decision with shop industry, entities, catalog/docs needs, reason, and heuristic confidence. The decision is logged in the RAG run. Confidence is telemetry only; it is not a probability and does not trigger an LLM call. Existing action rules remain authoritative. |
| 2. Follow-up entity context | Updated | Short product follow-ups resolve from the latest unambiguous customer-selected product in bounded history, or one exact product in the latest bot/staff reply. A new unresolved SKU/product hint cannot inherit an older item. Context is derived from messages; no new persistent `active_entity` column or migration was added. |
| 3. Ask for missing fields | Existing configurable flow retained | Business requests and service/rental collection already use shop-configured `collection_fields` and ask for missing fields one at a time. No hard-coded fashion/beauty/electronics slots were added to product recommendations because shops do not have a reliable shared slot profile; guessing would create unnecessary questions. |
| 4. Vietnamese BM25 terms | Updated | Added `áo phông`, `KCN`, and `sz` as alternatives in lexical concept groups used by `query_terms()` in `_retrieve_lexical()`. These are alternatives within a concept, not extra AND constraints. Broader per-industry synonym dictionaries remain dependent on measured query evidence. |
| 5. Grounded numbers | Existing guard retained | Serving already checks citations, cited numbers/prices, and authoritative live CRM product evidence in `has_valid_citations()`. The separate duplicate numeric guard proposed during implementation was removed after review because it could accept unrelated facts or reject valid formats. This check is a safety gate, not a guarantee that every cited passage semantically supports every claim. |
| 6. Learn from resolved handoffs | Updated | FAQ export now pairs a handoff to its triggering inbound message ID when available, bounds the staff reply to that turn, and marks every row `pending_human_review`. It never auto-ingests staff answers into the knowledge base. |
| 7. RFM personalization | Existing consent-gated flow retained | `rag_personalization_weights()` already supplies customer/product signals only when shop-level extraction is enabled and the customer has current personalization consent. RFM remains a product recommendation signal; this pass does not use it to choose knowledge evidence or alter answers. |

## Review and verification

- Read-only second-agent review used model `gpt-6-sol`; a separate `GPT-6 Sol Light` variant was not available to that agent. The agent initially missed that the lexical aliases were wired into retrieval; after checking the call path it corrected its review and confirmed point 4 is integrated.
- The review's main cautions were retained: router confidence is not calibrated, shop-specific required slots need shop configuration, staff answers remain unapproved candidates, and citations do not replace human evaluation of answer semantics.
- Focused regression set: **23 passed** (`20.64s`), covering structured routing including unlabelled multi-segment SKU, lexical aliases, exact SKU isolation, conversation follow-ups, product resolution, and handoff pairing.
- `py_compile` passed for changed Python modules/scripts; `git diff --check` passed. Line-ending normalization warnings from Git are informational.
- No migration, live server, external messaging, commit, or push was performed.

## Remaining measurement boundary

The changes improve route observability, exact follow-up handling, lexical matching, and FAQ candidate pairing. They do not prove an overall RAG accuracy increase yet. Compare the same approved queries before/after by intent and shop before widening the synonym set or introducing industry-specific required slots. The wider RAG/CRM suite previously had 186 passes and two follow-up regression failures; both failures were fixed and their regression cases passed in the final focused run, but the entire wider suite was not rerun after those fixes.
