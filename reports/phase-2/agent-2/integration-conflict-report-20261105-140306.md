# Phase 2.2 integration conflict report

## Worktree status

The physical workspace path is separate from the six sibling CRM worktrees
listed by `git worktree list --porcelain`. The current checkout contains the
Phase 1/1.1 source snapshot, but it also contains extensive uncommitted Agent
1/RAG work. No reset, clean, stash, merge or checkout operation was used.

## Overlap matrix

| File | Existing dirty ownership | Phase 2.2 addition | Handover risk |
|---|---|---|---|
| `backend/app/core/config.py` | Agent 1/RAG settings are uncommitted | One default-OFF flag | Low textual conflict; recheck placement when Agent 1 stabilizes |
| `backend/app/services/conversation_graph.py` | Large Agent 1 Graph/RAG changes are uncommitted | Bridge call, TurnState fields, plan/workflow/metadata handoff | High; manually reapply after the Agent 1 baseline is committed |
| `backend/app/services/sales_journey_engine.py` | Phase 2 Agent 2 file | Optional precomputed `BrainResolution` | Low; preserve as contract API |
| `backend/app/services/sales_journey_graph_bridge.py` | New Phase 2.2 file | Graph adapter and persistence read seam | Low; review against final Graph contracts |
| `backend/tests/test_sales_journey_graph_bridge.py` | New Phase 2.2 file | 13 offline contract tests | Low |
| `conversation_turn_service.py`, `auto_reply_service.py` | Existing turn/message owner | No source change; reused metadata seam | Medium; regression test after Agent 1 changes |

## Required controlled integration

Do not merge this dirty worktree directly. After Agent 1 stabilizes the Graph,
the integration owner should reapply only the Phase 2.2 hunks, run the full
supported test suite, verify the flag is still OFF in trusted server config,
and inspect the final diff for duplicate Needs Discovery, planner bypass,
Answer Guard bypass, transaction side effects and cross-tenant reads.

No conflict was resolved by overwriting Agent 1 files in this pass. No commit
or merge artifact was created.
