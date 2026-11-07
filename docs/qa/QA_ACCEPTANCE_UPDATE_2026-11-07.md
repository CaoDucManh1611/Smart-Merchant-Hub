# QA acceptance update — 2026-11-07

## Scope and safety

- Repository: `C:\Users\Administrator\Documents\Codex\2026-09-03\referenced-chatgpt-conversation-this-is-an\work\smart-merchant-hub`
- Branch/HEAD: `codex/rag-rfm-all-updates-20261104` / `c6895046f69773ed40db83ecc053faabce911e18`
- No application source was changed in this QA continuation. Existing dirty files and lock artifacts were preserved. `git diff --check` returned exit 0.
- Backend/frontend HTTP probes were read-only. PostgreSQL tests used a new local PostgreSQL 16 disposable container with tmpfs storage, bound to `127.0.0.1:55439`; no production or existing CRM DB connection was used. Synthetic DB container was removed after the run.
- No provider calls, customer messages, migrations, commits, pushes, or deployments were performed.

## Results

| Gate | Result | Evidence and limits |
|---|---|---|
| Local backend | PASS, read-only health | `GET http://127.0.0.1:8000/health` returned 200 with status `ok`. This proves process health only. |
| Local frontend | PASS, HTTP only | `GET http://127.0.0.1:5173/` returned 200 (472 bytes). This is not a browser/UI test. |
| Browser UI / desktop-mobile E2E | NOT VERIFIED | Codex browser control timed out while attaching/focusing the tab. A previous browser-context attempt also recorded connection refusal while shell HTTP returned 200. No login, click, CRUD, console/network, or screenshot acceptance was claimed. See `evidence-20261107/browser-blocker.txt`. |
| PostgreSQL tenant/session regression | PARTIAL, disposable DB | 16 selected tests passed with the PostgreSQL-configured runner. The direct transaction-local `search_path` isolation case exercised PostgreSQL; API isolation cases use synthetic test fixtures and are not claimed as PostgreSQL role/ACL runtime proof. Raw output/XML: `postgres-final-20261107.log`, `postgres-final-20261107.xml`. |
| PostgreSQL memory/consent regression | PASS, disposable DB | 51 tests passed across conversation memory and RAG feedback-consent tests. The harness's explicit dialect test printed `postgresql`. Logs: `postgres-consent-20261107.log`, `postgres-dialect-confirmation-20261107.log`. |
| Consent revoke/write race | PASS for the reproduced transaction sequence; overall gate remains partial | Two real PostgreSQL sessions: revoke waited on the memory writer's customer-row lock; after writer commit, revoke inserted its state and purged persisted memory; post-revoke read returned no active memory. This validates the lock/write/purge sequence using the actual service helpers and synthetic rows. It does not exercise the authenticated HTTP endpoint or every personalization side effect end-to-end, so do not treat the broader consent/privacy gate as closed. Script/log: `scripts/postgres-consent-race-probe.py`, `postgres-consent-race-probe-20261107.log`. |
| PostgreSQL least-privilege role ACL | NOT VERIFIED | The disposable DB bootstrap role reported `rolsuper=true`; this run cannot validate the application's production role privileges. |
| Full Alembic migration | NOT RUN / NOT VERIFIED | `alembic` CLI is unavailable in this workspace PATH; `backend/.venv` has no installed Alembic distribution and `python -m alembic` has no module entry point. A separate empty scratch database was created; the failed launcher did not apply migrations. The database was used only afterward for synthetic ORM-based concurrency checks. |
| Existing full regression | Prior QA evidence only; not rerun here | Existing report records backend 2,294 passed / 3 skipped and frontend 327 passed / production build passed. No application source changed in this continuation, so these counts are cited from `docs/qa/QA_RETEST_2026-11-07.md`, not represented as newly run. |
| Live RAG answer quality | NOT MEASURED | No LLM/provider call was made. Offline tests do not establish answer quality. |

## Release decision

`LOCAL_API_HEALTH=PASS`
`LOCAL_FRONTEND_HTTP=PASS`
`TARGETED_PYTEST=67 unique cases passed across the selected runs; the direct PostgreSQL and fixture-backed portions are separated above`
`POSTGRESQL_TARGETED=PASS for the 51 memory/consent cases and direct search_path case; no production-role ACL claim`
`CONSENT_RACE_SEQUENCE=PASS (synthetic two-session PostgreSQL probe)`
`CONSENT_PRIVACY_GATE=PARTIAL / OPEN pending authenticated endpoint-level validation and owner-approved retention/purpose policy`
`BROWSER_UI_E2E=NOT_VERIFIED`
`POSTGRESQL_MIGRATIONS=NOT_VERIFIED`
`POSTGRESQL_ROLE_ACL=NOT_VERIFIED`
`RAG_ANSWER_QUALITY=NOT_MEASURED`
`PRODUCTION_READY=NO-GO`

Local backend/frontend processes respond to read-only probes, but a complete synthetic UI demo is not verified and should not be presented as QA-accepted. Production acceptance remains blocked by browser UI E2E, migration and least-privilege role verification, full consent/privacy acceptance, and live answer-quality evidence.

## Artifact inventory

All new artifacts are under `docs/qa/evidence-20261107/`. Raw pytest logs/XML, read-only runtime probes, concurrency-probe script/log, migration blocker note, and exit-code/status files are retained. `source-scope-final.txt` records the final tracked-source scope and clean diff check.
