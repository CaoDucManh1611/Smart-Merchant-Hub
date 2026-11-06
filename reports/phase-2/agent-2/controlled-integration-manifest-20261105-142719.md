# Smart Merchant Hub Phase 2.4 controlled integration manifest

_Preparation only. No merge, cherry-pick, commit or Agent 1 worktree mutation was performed._

## Transfer set

Standalone Phase 2 modules:

- `backend/app/services/sales_journey_contracts.py`
- `backend/app/services/sales_journey_policy.py`
- `backend/app/services/sales_journey_adapter.py`
- `backend/app/services/sales_journey_engine.py`
- `backend/app/services/sales_journey_graph_bridge.py`

Phase 2 tests:

- `backend/tests/test_sales_journey_engine.py`
- `backend/tests/test_sales_journey_policy.py`
- `backend/tests/test_sales_journey_integration_contract.py`
- `backend/tests/test_sales_journey_graph_bridge.py`

The last file includes the Phase 2.4 real SQLite round-trip regression and must move with the other tests.

## Overlapping hunks to reapply semantically

1. `backend/app/core/config.py`: retain only the trusted setting `SALES_JOURNEY_ENGINE_ENABLED: bool = False` at the Agent 1 config location. Do not replace the file or overwrite unrelated RAG/config settings.
2. `backend/app/services/conversation_graph.py`: reapply the minimal Phase 2 hunks against the final Agent 1 file:
   - five `TurnState` journey fields;
   - one flag-guarded bridge call after trusted industry/Needs Discovery/memory context;
   - precomputed `BrainResolution` handoff;
   - journey plan/workflow consumption in `model_plan` and `_workflow_for_state`;
   - journey metadata on shortcut, handoff, capability-denied and final results;
   - state fields in the Graph invocation.
3. Do not apply the current dirty Graph file wholesale. Preserve Agent 1's final planner, authorization, RAG, Answer Guard, workflow and tenant changes.
4. `conversation_turn_service.py` and `auto_reply_service.py` normally require no Phase 2 source change; verify their existing metadata seam instead.

## Dependencies

- Python 3.12-compatible supported backend environment.
- `pytest==9.0.2`.
- `langgraph==1.2.16` for Graph runtime.
- `payos==1.1.0` for workflow/chatbot import paths.
- SQLAlchemy/Pydantic versions compatible with the final backend requirements.
- Disposable isolated test DB only; no production DB.

## Safe application order

1. Wait for the Agent 1 baseline to be committed or otherwise explicitly frozen and record its path, branch, HEAD and clean/dirt status.
2. Copy/reapply the five standalone modules and four Phase 2 test files.
3. Reapply the one config flag hunk and assert default OFF.
4. Reapply Graph changes by semantic anchors, never by replacing the whole file.
5. Run compileall and the 52 Phase 2 tests.
6. Run Phase 1 Sales Brain, Phase 1.1 Capability Registry, Graph, workflow, chatbot, RAG, catalog, recommendation, tenant and Answer Guard regressions with the flag OFF.
7. Run a mocked flag-ON Graph test for exactly one engine call, no duplicate discovery, authorization, deterministic shortcuts, Answer Guard, no unconfirmed transaction and fallback.
8. Run the real isolated DB two-turn path and delivery/retry/corruption/TTL cases.
9. Review the final diff for providers, migrations, side effects, cross-tenant reads and any production flag change.

## Common exit test matrix

| Area | Status | Evidence or next gate |
|---|---|---|
| Phase 1 Universal Sales Brain | PASS | 21 non-Graph Capability/Sales Brain tests pass; Graph subset is blocked. |
| Phase 1.1 Capability Registry | PASS | Capability Registry tests pass in the offline snapshot. |
| Phase 2 Sales Journey Engine | PASS | 52 Phase 2 tests pass. |
| LangGraph flag OFF | BLOCKED | Default and source guard pass; real Graph smoke test needs `langgraph`. |
| LangGraph flag ON | BLOCKED | Offline bridge/source contract passes; runtime mocked Graph test needs `langgraph`. |
| Catalog and RAG | NOT RUN | Broader serving/routing collection is blocked by `payos`; run after supported environment is available. |
| Recommendation | NOT RUN | No broad recommendation runtime run in this controlled pass. |
| Workflow authorization | BLOCKED | Workflow API collection reaches missing `payos`; engine fail-closed contracts pass. |
| Chat/stream and auto-reply | BLOCKED | Chatbot routing collection reaches missing `payos`; metadata path was source-audited. |
| Tenant isolation | PASS | Real SQLite tenant/conversation/customer mismatch checks return empty. |
| Multi-turn persistence | PASS | Real isolated SQLite two-turn round trip loads version 2 from sent state. |
| State corruption and TTL | PASS | Corrupt schema is ignored; stale state contract test passes. |
| Answer Guard | PASS static / NOT RUN runtime | `has_valid_citations` remains in compose; runtime Graph citation test awaits `langgraph`. |
| No extra LLM calls | PASS offline / NOT RUN runtime | Engine is deterministic and precomputed brain resolution is tested; runtime call-count check awaits Graph. |
| No unconfirmed transaction | PASS | Offer actions have no transaction/side effect and do not execute workflows. |
| Failure fallback | PASS static / NOT RUN runtime | Bridge exception path is guarded; runtime fault injection awaits Graph environment. |

## Rollback

Set the trusted server flag back to `False`. This restores the legacy planner path without deleting state or running a migration. If code rollback is needed, remove only the approved Phase 2 hunks after preserving the Agent 1 baseline.

## Readiness

Manifest prepared: YES. Controlled integration executed: NO. Current state: `WAITING_FOR_BASELINE` because Agent 1 has 85 unresolved full-backend failures and no runtime acceptance.
