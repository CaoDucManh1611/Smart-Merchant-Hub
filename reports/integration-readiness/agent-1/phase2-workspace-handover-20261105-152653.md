# Smart Merchant Hub — Agent 2 isolated Phase 2 workspace handover

_Captured 2026-11-05 15:27:42 +07:00._

## Workspace identity and isolation

- **Primary workspace:** `C:\Users\Administrator\Documents\Codex\2026-09-03\referenced-chatgpt-conversation-this-is-an\work\smart-merchant-hub`
- **Primary branch / HEAD:** `codex/rag-rfm-all-updates-20261104` / `92ae7e34c532d3d5b331e3c7343dcd9a20375f61`
- **Agent 2 workspace:** `C:\Users\Administrator\Documents\ChatGPT\smh-phase2-privacy-isolated`
- **Agent 2 branch / HEAD:** `codex/phase2-privacy-isolated-20261105` / `92ae7e34c532d3d5b331e3c7343dcd9a20375f61`
- The two canonical directory paths differ; Agent 2 has a separate working directory and branch.
- Primary source files were unchanged during capture. Only this handover and its manifest are added under the permitted primary `reports/` path.
- Snapshot captured 70 tracked changed files and 177 reviewed untracked files. The destination's captured Git status matched the primary exactly before verification logs were added.
- The primary HEAD and branch remained unchanged.

## Snapshot and hash verification

- Captured binary patch SHA-256: `994CE615221FAEC86018E16BCC58C6676568098572D6F0278D5C8EE62A68CEB4` (applied only in Agent 2 workspace).
- File manifest: `reports/integration-readiness/agent-1/phase2-source-manifest-20261105-152653.csv`.
- Manifest SHA-256: `E095E60A3120B04C0E0973512611A124E2DC603B8B4589223E8A719B51622721`.
- Manifest entries: **247** (70 tracked changed source/test files + 177 untracked allowlisted files).
- Final source-to-destination SHA-256 mismatches: **0 / 247**.
- The 70 tracked files were patched in the destination, then byte-copied from the unchanged source where Git's CRLF conversion would otherwise make byte hashes differ. All final hashes match the captured manifest.
- Allowlist scan: 0 high-confidence credential/token/private-key matches; 0 non-test email domains. One test fixture contains phone-shaped synthetic test values. No untracked `.env`, database, SQLite, Python cache, virtualenv, `node_modules`, or `.migrationdeps` paths were transferred. Ignored files were not copied.
- Required Phase 2 contracts, engine, policy, adapter, Graph bridge, and four Phase 2 tests are present and hash-verified. Universal Sales Brain and Capability Registry plus their tests are also present.
- `SALES_JOURNEY_ENGINE_ENABLED: bool = False` verified in `backend/app/core/config.py`.

## Database and Git object-store limitation

`backend/test.db` is a tracked file at the shared HEAD. Its index entry is marked `skip-worktree` in the Agent 2 worktree and the file is **not materialized** there. No database file was copied. However, a Git worktree shares the primary repository's Git object store and history, so this does **not** remove the database blob from Git objects or provide a separate confidentiality boundary for Git history. Do not treat this worktree as an isolated clone for secrets/history access.

## Offline validation

| Check | Result | Evidence |
|---|---|---|
| `python -m compileall -q backend/app backend/tests/test_sales_journey_engine.py backend/tests/test_sales_journey_policy.py backend/tests/test_sales_journey_integration_contract.py backend/tests/test_sales_journey_graph_bridge.py` | PASS, exit 0, 1.27 s | `C:\Users\Administrator\Documents\ChatGPT\smh-phase2-privacy-isolated\reports\integration-readiness\agent-2\compileall-20261105.log` |
| `python -m pytest -q -p no:cacheprovider backend/tests/test_sales_journey_engine.py backend/tests/test_sales_journey_policy.py backend/tests/test_sales_journey_integration_contract.py backend/tests/test_sales_journey_graph_bridge.py` | BLOCKED before collection, exit 4 | `C:\Users\Administrator\Documents\ChatGPT\smh-phase2-privacy-isolated\reports\integration-readiness\agent-2\phase2-offline-pytest-20261105.log` |
| Block reason | `backend/tests/conftest.py` requires `DATABASE_URL` or `backend/.env`; neither is available in this isolated workspace. No fake URL or production DB was used. | See pytest log |
| Migration, provider, customer messaging | Not run | Out of scope |

Compile success is syntax evidence only; it does not establish Phase 2 privacy correctness or RAG quality.

## Files excluded and status

- `backend/test.db`: excluded from checkout, as above; still present in shared Git history/object store.
- Real `.env`/credentials: not present in transferred allowlist; no secrets were intentionally copied.
- Ignored files, caches, build output and runtime data: not copied.
- No source code in the primary repository was edited by this capture. No reset, clean, stash, commit, push, merge, migration, reindex, provider call, deployment or customer message occurred.

## Handover verdict

```text
WORKTREE_ISOLATED=YES
SNAPSHOT_COMPLETE=YES (all 247 manifest files; database working file intentionally not materialized)
HASH_VERIFIED=YES
TEST_DB_MATERIALIZED=NO
PRIMARY_UNMODIFIED=YES (source unchanged; only this permitted report and manifest were added)
READY_FOR_AGENT2_SOURCE_EDITS=YES
```

This handover only establishes a separate edit workspace and snapshot integrity. Phase 2 privacy changes are still not implemented/verified; consent/retention policy decisions remain blockers. The pytest collection blocker must be resolved with an approved offline test database configuration before claiming Phase 2 regression verification. No production acceptance is implied.

