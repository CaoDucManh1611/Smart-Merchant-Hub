# Smart Merchant Hub Phase 2.4 merge-conflict checklist

## Worktree evidence

- Phase 2 workspace: `C:\Users\Administrator\Documents\Codex\2026-09-03\referenced-chatgpt-conversation-this-is-an\work\smart-merchant-hub`.
- Branch: `codex/rag-rfm-all-updates-20261104`.
- HEAD: `92ae7e34c532d3d5b331e3c7343dcd9a20375f61`.
- Six other physical worktree paths are listed by Git; they are not this directory.
- The current directory contains uncommitted Agent 1/RAG changes and the Agent 1 report snapshot. No reset, clean, stash, checkout, merge or cherry-pick was used.
- Some sibling repositories reject read-only Git inspection with Git's dubious-ownership guard. No global safe-directory setting was changed. Their physical paths were not modified.

## Agent 1 baseline decision

Agent 1's latest report records `2,043 passed, 85 failed, 2 skipped`, no runtime verification and no acceptance. The dominant issue is capability provisioning/test-fixture alignment, with additional SQLite/harness and discrete baseline failures. Therefore:

`BASELINE STATUS = WAITING_FOR_BASELINE`

This is not a Phase 2 merge conflict resolution and must not be relabeled `MERGED`.

## Conflict matrix

| File | Phase 2 operation | Risk | Safe action |
|---|---|---|---|
| `backend/app/core/config.py` | Add/retain one default-OFF setting | Medium: file has Agent 1/RAG settings | Reapply one semantic field only; inspect final config. |
| `backend/app/services/conversation_graph.py` | Add bridge/state/metadata hunks | High: large Agent 1 Graph/RAG diff | Reapply by anchors after baseline freeze; never overwrite the file. |
| `backend/app/services/sales_journey_engine.py` | Keep optional `BrainResolution` parameter | Low | Transfer standalone file and preserve API. |
| `backend/app/services/sales_journey_graph_bridge.py` | Transfer new bridge | Low | Transfer standalone file; review ORM model contracts. |
| Phase 2 test files | Transfer tests | Low | Transfer all four, including SQLite round trip. |
| `conversation_turn_service.py` / `auto_reply_service.py` | No planned source edit | Medium contract dependency | Verify metadata handoff after Agent 1 changes. |
| Phase 1/1.1/RAG files | No Phase 2 operation | High | Do not copy from this dirty snapshot over Agent 1's final baseline. |

## Merge gate checklist

- [ ] Agent 1 baseline path and final commit/snapshot identified.
- [ ] Agent 1 85 failures triaged/accepted by owner.
- [ ] Supported environment contains LangGraph and PayOS.
- [ ] Default flag remains OFF.
- [ ] Only Phase 2 standalone files and approved hunks are applied.
- [ ] No duplicate Needs Discovery or planner bypass.
- [ ] Authorization and Answer Guard remain authoritative.
- [ ] Real isolated DB round trip passes.
- [ ] Full regression and mocked flag-ON checks pass.
- [ ] No production DB/provider/migration/reindex/flag activation.

Until the first two gates are closed, the safe action is to wait.
