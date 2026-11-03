# RAG catalog fixes from current shop chat

Date: 2026-11-03  
Branch: `codex/rag-improvements-20261102`

## Evidence reviewed

Reviewed the user's first 20 catalog-chat results for the current motorcycle-parts shop. The successful answers already returned the correct live catalog facts for the Wave Alpha sprocket kit, rear drum brake shoes, two NGK plugs, Vision roller set/belt, Wave Alpha and Sirius FI filters, DOT4 brake fluid, oil-type distinction, coolant, and inner tube.

Observed misses and grounding issue:

- Comparison of two explicit NGK SKUs fell through to a generic no-evidence response.
- Comparing tire sizes and asking about both left/right mirrors did not return the matching catalog rows.
- Asking what vehicle a product SKU is for did not enter the direct catalog detail route.
- The coolant answer added a manufacturer's mixing-ratio rationale that was absent from the catalog description.
- A direct SKU detail question about the 428H chain was not resolved in the supplied Telegram output.

## Changes made

- Added a tenant-catalog mention resolver that prioritizes exact SKU/name matches and uses distinctive catalog tokens for explicit shortened variants. It does not use embeddings or choose a nearest item.
- Expanded deterministic catalog comparison to recognize “khác nhau/khác gì” and compare multiple explicit items from live active catalog rows, including SKU pairs and product variants.
- Added multi-item price/stock replies for explicit requests that ask about each item, with per-item SKU, price, and available quantity.
- Routed exact SKU detail questions to current catalog descriptions; an unknown SKU now returns not-found instead of falling through to a generic answer.
- When the matched product description explicitly says not to add water, the answer repeats that instruction without inventing a manufacturer-ratio explanation.
- Changes are shared across tenants and do not add motorcycle-only rules.

## Verification boundary

- No automated tests were run during the code-edit pass.
- The Telegram bot was not messaged again. These source changes will affect it only after the backend process serving that bot runs this checkout/version.
- Comparison token matching and the chain SKU detail path still need regression evaluation in Telegram before claiming the failures are fixed in the live chat.
- No commit or push was performed; the branch already contained unrelated uncommitted changes before this pass.

## Runtime follow-up

- A read-only query of tenant `shop_7` confirmed all seven tested rows are present and active: the chain, both NGK plugs, both tire sizes, and both M10 mirrors. It also confirmed their current prices and stock quantities.
- The Telegram replies arrived while the Docker backend and worker processes had started before the edited Python files; the containers mount `backend/app` but do not run Uvicorn with `--reload`. This explains why those replies still followed the previous code.
- Restarted only `backend` and `worker` to load the mounted changes. Both reported healthy and `GET /health` returned `status=ok`.
- The new replies have not yet been rechecked in Telegram. No tests were run, and no commit or push was made.

## Follow-up from Telegram results

The user then supplied five additional live replies. The exact M10 left/right comparison was correct. The tire comparison still returned only 70/90-17, the chain SKU fell back to a generic uncertainty answer, and the coolant reply added an unsupported "standard ratio" explanation. The NGK comparison now returned both catalog items.

Read-only tenant DB inspection confirmed the tire request persisted both product IDs (70/90-17 and 80/90-17) in its recommendation metadata, while the saved reply body contained only the first item. Direct invocation of the current catalog reply function produced both tires and resolved the chain SKU to its live catalog row (428H, 104 links, 235,000 VND, available 13). The mismatch is consistent with a worker that had not loaded the current source or a divergent execution path; the backend and worker have now been restarted. The coolant catalog row explicitly says "không pha thêm nước" but the generic question matched multiple fuzzy products, so the deterministic guard did not claim the verified answer.

### Follow-up changes

- The explicit-item matcher now preserves exact hits and supplements a single exact hit with distinctive matches only when the query clearly asks about multiple items. This covers one exact tire size plus a second shortened size without widening single-item lookups.
- The water-use guard now identifies active catalog items by the specific "nước mát pha sẵn" name facets, then answers only if the description explicitly says not to add water. The answer no longer adds a manufacturer-ratio rationale.
- Restarted the local backend and worker after the edits. Both became healthy; `GET /health` returned `status=ok` with loaded/source revision `8bf23ae6252c120b`.

### Remaining verification

- Ask the same tire, coolant, and chain questions again in the Telegram test chat to confirm the reloaded worker sends the deterministic catalog answers.
- The user’s NGK result is good; the mirror comparison is good. The chain answer should state the catalog dimensions but must not promise vehicle fit without model/year or service-manual confirmation.
- No automated tests were run. No commit or push was performed.

## Graph-path consistency fix

The next Telegram sample showed the chain answer succeed, then fall back to the generic no-evidence message on the next identical query, then succeed again. The tenant database confirmed these were separate inbound turns and one outbound reply per turn. Worker logs identified the active path as `conversation_turn_service.dispatch_chatbot_turn` → `conversation_graph.graph_reply` (`intent=graph_answer`); this graph path planned and composed product facts through Groq instead of invoking the deterministic live-catalog reply helper. The worker logs also showed Groq HTTP 429 responses during these turns, matching the intermittent generic fallback.

Added a read-only catalog shortcut in the active graph path for product facts, attribute questions, explicit comparisons, and premixed-coolant instructions. It reuses the same tenant-scoped deterministic catalog resolver, excludes service/rental and explicit order/payment requests, records the selected route in `RagRunLog`, and returns without depending on the planner or answer LLM. This applies across shop industries and is limited to read-only product questions.

Restarted backend and worker after the graph-path change. Both are healthy; `GET /health` returned `status=ok` with loaded/source revision `539624900d2e31a3`.

Still required: repeat the chain question twice plus the tire comparison and coolant question in Telegram. This confirms the graph shortcut is active in the live path. No automated tests were run; no commit or push was performed.
