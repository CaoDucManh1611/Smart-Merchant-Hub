# RAG live-query precision corrections

Date: 2026-11-03

## Input

Reviewed the user's live Telegram results for cases 21–50. The reported failure patterns included Vietnamese grouped-currency budgets being misread, comparison follow-ups losing catalog constraints, warranty questions being routed as product ambiguity, and product suggestions drifting to a different model/category.

## Changes

- Added one VND budget parser shared by catalog discovery and recommendation matching. It recognizes grouped forms such as `200.000đ` / `200,000 VND`, shorthand such as `200k`, and decimal unit forms such as `1,5 triệu`.
- Preserved complete numeric dimensions such as `70/90-17` and `80/90-17` during catalog matching, so comparisons return the requested sizes rather than collapsing them into a generic tire match.
- Routed policy questions to policy retrieval before deterministic product identity, fitment, and catalog discovery logic. A tire warranty question can now reach warranty evidence instead of being intercepted by tire-size disambiguation.
- Prevented customer-specific product/category queries from going through the general popularity/RFM recommendation branch. That branch remains available for broad needs without an explicit catalog match.
- Added a conservative catalog-term scope to product suggestions. Rare query terms found in product names, descriptions, aliases, attributes, and compatibility metadata must also occur in the suggested item. If the requested model/variant cannot be matched, return the safe no-match reply instead of substituting another catalog segment.
- Kept the immediately preceding bot/staff product mention available to a follow-up even when the preceding answer already named only one winner, such as the cheaper item.

## Validation boundary

- Added a regression case proving a two-size tire query resolves exactly the requested 70/90-17 and 80/90-17 products.
- Ran `python -m pytest tests/test_chatbot_answer_routing.py tests/test_product_resolver.py -q`: **61 passed**. This includes comparison, recommendation, budget filtering, follow-up, fitment and resolver coverage.
- Installed the repository-pinned `langgraph==1.2.16` with its dependencies into the current user Python environment; no repository dependency files changed.
- Retested the previously uncollectable modules: `python -m pytest tests/test_conversation_context.py tests/test_conversation_graph.py -q` => **25 passed, 9 failed**. Seven failures are in conversation-graph behavior (several knowledge/calculation cases route to `product_not_found`); two are in conversation-context/recommendation coverage against the local PostgreSQL test database. These failures remain unresolved.
- The full backend suite was started but not completed after unrelated failures appeared early. No full-suite pass is claimed.
- `git diff --check` completed without whitespace errors for the touched source and test files.
- No Telegram messages were sent and the running bot was not restarted/deployed. These edits are local; live behavior will use them only after the correct backend instance is restarted or deployed.
- No commit or push was made. Existing unrelated workspace changes were preserved.

## Follow-up: requested regression tests

Date: 2026-11-03

- Fixed the catalog retrieval compatibility issue that made exact-price lookup, current-catalog citations, OCR evidence, and calculation/validation retries fail against the legacy PostgreSQL test schema. When structured catalog mapping tables are absent, lexical SKU retrieval is allowed only through the tenant-scoped legacy path; required structured attributes remain fail-closed.
- Allowed a `product_not_found` preliminary route to continue through graph tools, so current catalog and knowledge evidence can resolve a request before returning a miss.
- Updated the recommendation graph test to assert the intended deterministic rendering from live ranked catalog data (one planner LLM call), and supplied a realistic retrieved chunk so the saved trace is exercised.
- Requested nine tests: **9 passed**.
- Full affected modules: `python -m pytest tests/test_conversation_context.py tests/test_conversation_graph.py -q --tb=short` => **34 passed in 42.82s**.
- `compileall` and `git diff --check` passed for the touched source/test files. No migration, commit, or push was run.
