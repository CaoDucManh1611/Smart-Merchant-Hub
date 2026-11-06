# Smart Merchant Hub Phase 2 integration decision

_Final pre-merge checkpoint - Agent 2 - 2026-11-05._

## Current decision

```text
PHASE2_ALREADY_PRESENT_IN_AGENT1_WORKTREE: YES in the accessible shared snapshot
ACTIVE AGENT1 OWNERSHIP: UNVERIFIED
READY_FOR_CONTROLLED_INTEGRATION: NO - HOLD
MERGED: NO
```

The current physical path is the path recorded by the Agent 1 finalization report. It contains Agent 1/RAG changes, the current Graph/config changes and the Phase 2 modules. The six other Git worktrees are physically separate, but none is identified as the active Agent 1 worktree. Therefore there is no safe source-to-source merge boundary to exercise in this session.

## Graph hunks observed in the accessible snapshot

The following Phase 2 integration pieces are already present and must be reviewed against the final Agent 1 baseline later:

| Area | Observed behavior |
|---|---|
| Feature flag | `SALES_JOURNEY_ENGINE_ENABLED` defaults to `False` in `backend/app/core/config.py`. |
| State bridge | `conversation_graph.py` carries journey clarification, plan, workflow and metadata fields. |
| Invocation | A single guarded `build_graph_journey_bridge` call is made when the flag is enabled; exceptions fall back to legacy behavior without retry. |
| Planner | The precomputed journey plan is consumed before the legacy planner path. |
| Safety | Existing authorization, deterministic shortcut and Answer Guard paths remain visible in the dirty Graph file; runtime proof is still blocked. |
| Persistence | `sales_journey_graph_bridge.py` loads only scoped, sent outbound metadata and maps the next action into the existing plan without creating side effects. |
| Engine API | The engine accepts an optional precomputed brain resolution to avoid a duplicate adapter call. |

This is an inventory of the accessible dirty snapshot, not a claim that the final Agent 1 baseline is compatible.

## Agent 1 baseline freshness

The last signed full baseline remains the Agent 1 report with `2,043 passed, 85 failed, 2 skipped, 139 warnings, 37 subtests`. Later evidence is partial only:

- The 14:35 focused run had 2 failures and 28 passes.
- The 14:37 focused rerun had 30 passes and 1 skipped.
- The 14:40 offline backend run contains only start lines; there is no matching XML or completion result.

The focused rerun is not a replacement for the full baseline and does not establish acceptance.

## Controlled integration procedure for a later isolated snapshot

1. Establish and record two distinct physical worktree paths and owners.
2. Transfer only the standalone Phase 2 modules and tests.
3. Manually reapply the semantic `config.py` feature-flag hunk and the minimal `conversation_graph.py` adapter/state/plan/metadata hunks.
4. Do not copy whole `conversation_graph.py` or `config.py`; do not overwrite Phase 1/1.1 Agent 1 work.
5. Review persistence writer/loader changes separately and keep `InMemoryJourneyStateAdapter` test-only.
6. Run Phase 2 tests, Graph runtime tests in an environment containing LangGraph, then the full backend regression.
7. Keep the flag OFF for rollback; verify legacy tests and legacy response behavior with the flag OFF.

## Compatibility gates

The accessible Phase 2 suite passed offline (`52 passed`), and the workflow/chatbot subset passed (`82 passed`). The following gates remain open: LangGraph runtime, bounded privacy schema and retention/consent policy, a fresh full Agent 1 baseline, and verified ownership separation.

**INTEGRATION DECISION: HOLD. No merge, cherry-pick, copy, reset or stash was performed.**
