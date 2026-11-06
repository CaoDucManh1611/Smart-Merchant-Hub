# Phase 2.3 controlled integration readiness

_Merge preparation only; no merge, cherry-pick or commit was performed._

---

## Transfer set

Move/reapply these Phase 2 files after Agent 1 stabilizes:

- `backend/app/services/sales_journey_contracts.py`
- `backend/app/services/sales_journey_policy.py`
- `backend/app/services/sales_journey_adapter.py`
- `backend/app/services/sales_journey_engine.py`
- `backend/app/services/sales_journey_graph_bridge.py`
- `backend/tests/test_sales_journey_engine.py`
- `backend/tests/test_sales_journey_policy.py`
- `backend/tests/test_sales_journey_integration_contract.py`
- `backend/tests/test_sales_journey_graph_bridge.py`

Reapply only the approved Phase 2 hunks in:

- `backend/app/core/config.py` — `SALES_JOURNEY_ENGINE_ENABLED=False`.
- `backend/app/services/conversation_graph.py` — bridge call, TurnState
  fields, plan/workflow/metadata handoff, and final/shortcut metadata.

Normally do not change `conversation_turn_service.py` or
`auto_reply_service.py`; their existing CrmJob and Message metadata path is the
selected persistence owner.

## Safe application order

1. Preserve the Agent 1 baseline and record `git status`/branch/HEAD.
2. Apply the four standalone engine/adapter modules and their tests.
3. Apply the config flag hunk and confirm its default is `False`.
4. Apply Graph hunks by semantic anchors, not line numbers.
5. Run compileall and the 51 offline tests.
6. Run the supported-environment Graph, chatbot, workflow, RAG and capability
   suites with the flag OFF.
7. Run mocked flag-ON tests for one engine call, no duplicate Needs Discovery,
   authorization, Answer Guard, deterministic shortcuts and fallback.
8. Run isolated two-turn persistence tests for exact tenant/conversation/
   customer scope, stale/corrupt state, delivery unknown and handoff failure.
9. Review the diff for provider calls, transaction creation, migrations,
   broad refactors and cross-tenant reads.

## Acceptance matrix

| Area | Current evidence | Merge prerequisite |
|---|---|---|
| Flag OFF | Settings default and source guard | Real Graph OFF smoke test |
| Flag ON | 21 bridge tests and source ordering checks | Runtime mocked Graph test |
| Authorization | Capability Registry + engine tests | Full Graph authorize-node test |
| Answer Guard | Source seam check; existing tests available | Runtime citation/claim tests |
| Persistence | Two-turn offline adapter test and source audit | Real isolated DB round trip |
| Workflow safety | Offer mapping and no-side-effect tests | Booking/order/quote integration tests |
| Runtime | Not verified; missing packages | Agent 1 supported environment |

## Rollback

Set `SALES_JOURNEY_ENGINE_ENABLED=False`. This restores the legacy planner
without a data migration. Do not delete state rows or reset the worktree as a
rollback action.

## Known conflicts

`conversation_graph.py` and `config.py` already contain uncommitted Agent 1/
RAG changes in this worktree. The Graph runtime dependency is also absent from
the local test snapshot. These are controlled-integration blockers, not
permission to edit or merge Agent 1 work.
