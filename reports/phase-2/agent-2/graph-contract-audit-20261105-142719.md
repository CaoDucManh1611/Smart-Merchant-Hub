# Smart Merchant Hub Phase 2.4 Graph contract audit

## Evidence boundary

The bridge and source-order contracts are verified offline. The real Graph cannot be imported in the available environment because `langgraph` is missing. The status is therefore `STATIC/CONTRACT VERIFIED`, not `RUNTIME VERIFIED`.

## Contract review

| Contract | Result | Evidence |
|---|---|---|
| Trusted feature flag OFF | PASS offline | `backend/app/core/config.py:145` defaults `SALES_JOURNEY_ENGINE_ENABLED` to `False`; the flag is server configuration only. |
| Flag ON invokes the bridge once | PASS static/offline | `conversation_graph.py:381-418` contains one guarded bridge call; the 52-test suite covers bridge mapping and source ordering. |
| No duplicate Needs Discovery from the engine | PASS offline | `BrainResolution` is passed into the engine; the dedicated test rejects a second adapter call. Existing discovery recomputation is guarded by `needs_discovery_recomputed`. |
| Journey action is a plan, not authorization | PASS static | `graph_plan_for_decision` only creates the existing plan shape. `authorize_plan` remains the next Graph node at `conversation_graph.py:280`. |
| Deterministic shortcuts preserved | PASS static | The bridge runs before shortcut checks, but existing safe shortcut returns remain authoritative and carry journey metadata. |
| Capability authorization before protected tools | PASS static/offline | Journey plans are rechecked by the existing authorization resolver; disabled RETAIL/ORDER/APPOINTMENT paths are covered by Phase 2 tests. |
| Answer Guard preserved | PASS static | `has_valid_citations` remains in `compose` at `conversation_graph.py:1266`; no bridge path returns an answer around that node. |
| No default extra LLM call | PASS offline/static | Engine decisions report `llm_calls=0`, `network_calls=0`; passing `BrainResolution` avoids a second discovery adapter call. Runtime call-count proof is blocked. |
| No transaction from CLOSING/offer | PASS offline | Booking, quote and order actions are offers/plans only; `transaction_created=False` and `side_effects=[]`. |
| Handoff failure is not success | PASS static | Existing Graph checks the returned ticket/status before `graph_handoff`; failure returns `graph_handoff_failed`. |
| Engine/bridge exception fallback | PASS static | The guarded call catches errors, logs the type, and continues to the legacy planner without retry. Runtime fallback is not executable here. |
| Cross-tenant state retrieval | PASS offline | Loader filters exact business, conversation, customer, outbound direction and `sent` status; real SQLite scope tests pass. |

## Current source anchors

- `backend/app/core/config.py:145`
- `backend/app/services/conversation_graph.py:280`
- `backend/app/services/conversation_graph.py:381-422`
- `backend/app/services/conversation_graph.py:631-640`
- `backend/app/services/conversation_graph.py:1266-1269`
- `backend/app/services/conversation_graph.py:1357-1364`
- `backend/app/services/conversation_graph.py:1371-1403`
- `backend/app/services/sales_journey_graph_bridge.py:98-116`

## Open runtime checks

The integration owner must still execute one real flag-OFF Graph smoke test and one mocked flag-ON Graph test in an environment containing LangGraph. Those tests must assert bridge call count, discovery call count, authorization, Answer Guard, deterministic shortcuts, workflow confirmation, handoff failure and legacy fallback. Until then, both flag-OFF and flag-ON are contract-level evidence only.
