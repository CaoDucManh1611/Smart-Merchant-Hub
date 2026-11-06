# Smart Merchant Hub Phase 2 integration readiness

_Controlled integration decision - 2026-11-05 15:02 +07:00._

## Status

```text
PHASE2_ALREADY_PRESENT_IN_AGENT1_WORKTREE: YES in the accessible shared snapshot
FEATURE FLAG DEFAULT: OFF
GRAPH RUNTIME: BLOCKED
BASELINE COMPATIBLE: NOT VERIFIED
READY_FOR_CONTROLLED_INTEGRATION: NO - HOLD
```

## Existing integration inventory

The shared snapshot already contains the expected semantic pieces:

- `SALES_JOURNEY_ENGINE_ENABLED = False` in `backend/app/core/config.py`.
- `TurnState` journey fields in `backend/app/services/conversation_graph.py`.
- One guarded bridge invocation after industry/Needs Discovery preparation.
- Precomputed brain resolution passed into the engine to avoid duplicate discovery.
- Planner mapping, authorization, deterministic shortcut and Answer Guard paths remain in the current Graph source.
- Journey metadata is carried through the existing collection/turn writer path.
- `sales_journey_graph_bridge.py` loads only scoped, sent outbound state and performs no tool/workflow/provider/transaction action.

This is an inventory of a dirty shared snapshot, not a verified merge result.

## Safe patch plan after isolation

| Order | Action | Gate |
|---:|---|---|
| 1 | Create a separate Agent 2 or integration snapshot with owner marker | Physical paths and HEADs differ |
| 2 | Transfer standalone Phase 2 modules and tests only | No Phase 1/1.1 overwrite |
| 3 | Reapply the minimal feature-flag hunk | Default remains OFF |
| 4 | Reapply minimal Graph state/bridge/planner/metadata hunks manually | Preserve Graph ownership and conflicts |
| 5 | Apply privacy hardening and journey-specific retention policy | Privacy regression suite green |
| 6 | Run Graph import and flag-OFF/flag-ON tests | LangGraph environment available |
| 7 | Run full offline backend and approved PostgreSQL tests | Baseline has no unexplained regressions |
| 8 | Keep rollback as flag OFF | Legacy path remains green |

## Files requiring later review

- `backend/app/services/sales_journey_contracts.py`
- `backend/app/services/sales_journey_adapter.py`
- `backend/app/services/sales_journey_graph_bridge.py`
- `backend/app/services/conversation_turn_service.py`
- `backend/app/services/auto_reply_service.py`
- `backend/app/services/privacy_service.py`
- `backend/app/core/config.py`
- `backend/app/services/conversation_graph.py`
- New privacy and Graph regression tests under `backend/tests/`

No file above was changed in this checkpoint. Do not copy entire `conversation_graph.py` or `config.py`; apply reviewed semantic hunks only after ownership is resolved.

**INTEGRATION READINESS: HOLD. Feature flag OFF remains the rollback control.**
