# Smart Merchant Hub — Final Acceptance Blocker Closure

Date: 2026-11-05  
Workspace: `C:\Users\Administrator\Documents\Codex\2026-09-03\referenced-chatgpt-conversation-this-is-an\work\smart-merchant-hub`  
Branch: `codex/rag-rfm-all-updates-20261104`  
HEAD: `92ae7e34c532d3d5b331e3c7343dcd9a20375f61`

## Result summary

| Check | Status | Evidence / blocker |
|---|---|---|
| `POSTGRES_16_FILE_SUITE` | **PASS** | All 16 requested test files passed on disposable PostgreSQL 16: 259 passed, 3 subtests passed, exit 0. |
| `ALEMBIC_HEAD_VERIFIED` | **PASS** | Exactly one tenant head: `20261104_0017`, parent `20261103_0016`; no migration was run. |
| `DB_ROLE_ACL` | **NOT_VERIFIED** | A synthetic least-privilege role passed ACL probes. The configured application/runtime role was not available for inspection. |
| `TENANT_SCHEMA_ISOLATION` | **PASS — TEST SCOPE** | PostgreSQL tenant-routing/scoped-query/API/RAG tests passed; synthetic role could not read/write another tenant or platform schema. Production ACL/runtime remains unverified. |
| `POSTGRES_CONNECTION_POOL` | **PASS — TEST SCOPE** | `test_database_boundaries.py`: 2 passed, including transaction-local `search_path` reset between sessions. |
| `CONSENT_RACE` | **FAIL — OPEN** | Deterministic two-session PostgreSQL probe reproduced stale in-flight memory use after revocation. Fresh subsequent read was denied. No provider or outbound send was invoked. |
| `BROWSER_UI` | **NOT_VERIFIED** | Browser automation initialization was blocked by the runner (`node:process` import rejected). No visual or responsive UI check was completed. Manual checklist and isolated launch commands are below. |
| `RAG_ANSWER_QUALITY` | **NOT_VERIFIED — NOT_MEASURED** | A 20-case synthetic answer-quality set is prepared. No approved provider credentials were available or used; no generated answers were scored. |
| `PRIVACY_OWNER_DECISIONS` | **NOT_VERIFIED** | Retention, purpose, consent-without-row and revocation policy decisions still require the data/privacy owner. |
| `BACKEND_REGRESSION` | **PASS — TARGETED** | PostgreSQL 16 targeted suite above passed. Recorded full offline baseline remains 2,198 passed / 6 skipped; it was not rerun because this acceptance made no backend source changes. |
| `FRONTEND_REGRESSION` | **PASS — RECORDED BASELINE** | 327 frontend tests and production build passed in the preceding acceptance; frontend source was not changed in this closure. |
| `LOCAL_DEMO_READY` | **NOT_VERIFIED** | Earlier synthetic HTTP/API smoke is recorded, but browser UI acceptance could not be performed in this run. |
| `STAGING_READY` | **NOT_VERIFIED** | No staging environment or owner-authorized staging credentials supplied. |
| `PRODUCTION_READY` | **FAIL — NO** | Open consent race, unapproved privacy decisions, unverified runtime DB role, browser acceptance and answer-quality gate prevent acceptance. |

Machine-readable status:

```text
POSTGRES_16_FILE_SUITE=PASS
ALEMBIC_HEAD_VERIFIED=PASS
DB_ROLE_ACL=NOT_VERIFIED
TENANT_SCHEMA_ISOLATION=PASS_TEST_SCOPE
POSTGRES_CONNECTION_POOL=PASS_TEST_SCOPE
CONSENT_RACE=FAIL_OPEN
BROWSER_UI=NOT_VERIFIED
RAG_ANSWER_QUALITY=NOT_VERIFIED_NOT_MEASURED
PRIVACY_OWNER_DECISIONS=NOT_VERIFIED
BACKEND_REGRESSION=PASS_TARGETED_POSTGRES
FRONTEND_REGRESSION=PASS_RECORDED_BASELINE_NOT_RERUN
LOCAL_DEMO_READY=NOT_VERIFIED
STAGING_READY=NOT_VERIFIED
PRODUCTION_READY=FAIL
```

## Source and workspace safety

- Preserved branch, HEAD and all existing working-tree changes. No reset, clean, stash, commit, push, merge or deployment was performed.
- At final capture before adding this report, `git status --porcelain=v1 --untracked-files=all` showed 273 entries. This task added the synthetic answer-evaluation JSONL and this report; no application source was changed.
- Rechecked the pre-existing 158-entry safe-source hash manifest: **158/158 hashes matched**, with zero missing or mismatched files. Manifest SHA-256: `b4acb89147e253cd64124d389653fa42bf8943f79f0ff20fdf098c824a905201`. The manifest excludes secrets, databases, dependencies, caches and reports; it does not contain the newly added evaluation dataset/report.
- `git status -- backend/test.db` was empty. The database file was not opened, read, copied or included in artifacts.
- PostgreSQL test data and role were synthetic. The disposable PostgreSQL 16 container used tmpfs, bound to loopback, and was stopped after testing; no matching container or listener remained on port 55432.
- No Groq, Gemini, embedding, payment, messaging or other external provider was called.

## PostgreSQL 16 regression evidence

The clean rerun was one invocation over the full requested 16-file set, not an aggregation of per-file reruns:

```text
python -m pytest -q tests/test_postgres_test_harness.py tests/test_tenant_context.py tests/test_tenant_scoped_queries.py tests/test_api_tenant_isolation.py tests/test_authenticated_tenant_session.py tests/test_conversation_memory_isolated.py tests/test_sales_journey_privacy.py tests/test_rag_feedback_consent.py tests/test_crm_job_worker.py tests/test_order_payments.py tests/test_subscription_payments.py tests/test_customer_order_actions.py tests/test_workspace_modules.py tests/test_tenant_migration_runner.py tests/test_conversation_turn_service.py tests/test_rag_tenant_isolation.py
```

Result: `259 passed, 3 subtests passed in 114.45s`; exit code `0`. The earlier stale migration-head assertion was corrected before this clean batch. Raw log:

`C:\Users\Administrator\AppData\Local\Temp\smh-final-acceptance-20261105\postgres-16-files-rerun-20261105.log`

Connection-pool/search-path check:

```text
python -m pytest -q tests/test_database_boundaries.py
```

Result: `2 passed in 4.59s`; exit code `0`. Raw log:

`C:\Users\Administrator\AppData\Local\Temp\smh-final-acceptance-20261105\postgres-connection-pool-rerun-20261105.log`

Alembic head check, run against the current primary source with `DATABASE_URL=sqlite://` and `ENVIRONMENT=test`:

```text
python -m alembic -c alembic-tenant.ini heads --verbose
```

Result: one head, `20261104_0017 (head)`, parent `20261103_0016`, exit code `0`. This inspected the revision graph only; it did not execute a migration. Raw log:

`C:\Users\Administrator\AppData\Local\Temp\smh-final-acceptance-20261105\alembic-heads-final-20261105.log`

### Synthetic database-role ACL probe

A disposable role had `NOSUPERUSER`, `NOCREATEDB`, and `NOCREATEROLE`; it received only the synthetic Shop A schema/table grants. It could read Shop A, could not access Shop B or platform schema, and could not create a table. Authenticated-session `search_path` was `smh_acl_shop_a, pg_catalog`. Cross-tenant read/write, platform read and DDL attempts were denied as expected.

This demonstrates the probe and grants for a synthetic role only. It does **not** establish the actual application role's configured grants, so `DB_ROLE_ACL=NOT_VERIFIED`. Raw log:

`C:\Users\Administrator\AppData\Local\Temp\smh-final-acceptance-20261105\postgres-synthetic-role-acl-20261105.log`

## Consent read/revocation race

A temporary probe, outside the repository, used two distinct PostgreSQL backend sessions and synchronization events with a synthetic customer:

```text
CONSENT_RACE_SYNTHETIC={'pid_a': 1960, 'captured_before_revoke': [91001], 'pid_b': 1961, 'context_used_after_revoke': [91001], 'fresh_read_after_revoke': []}
1 passed in 1.91s
```

Session A read reply memory while consent was granted and held it as in-flight context. Session B revoked consent and committed. The already-held context remained available to the in-flight turn; a fresh memory read returned empty. The probe did not call a real model, execute the full graph/provider boundary, or send an outbound message. It confirms the race is not closed and therefore remains **OPEN/FAIL**; it is not evidence that an external reply was actually sent after revocation.

Raw log:

`C:\Users\Administrator\AppData\Local\Temp\smh-final-acceptance-20261105\consent-race-probe-20261105.log`

No partial code patch was made. Closing this requires an owner-approved rule for revocation during an in-flight turn and a regression that covers the actual pre-model/use and outbound side-effect boundaries without holding a DB lock across generation.

## Browser UI acceptance and manual run

`BROWSER_UI=NOT_VERIFIED`. The supported browser runner rejected importing `node:process`; its bootstrap did not complete, so no browser tab was controlled. This is a tooling blocker, not evidence of an application UI defect. No login, responsive layout, console or browser-network assertions are claimed.

### Safe local launch commands

Run only from a source copy with `.env` and `backend/.env` absent, against a **disposable synthetic database**. Do not point these commands at an existing shop database or copy database files, uploads, backups or provider credentials from a live workspace. The PostgreSQL example binds only to loopback and stores data in tmpfs; it creates no persistent volume.

In the backend terminal, start the disposable database and create the two additional app databases:

```powershell
$localPassword = [guid]::NewGuid().ToString('N')
docker run --rm -d --name smh-acceptance-ui-pg --tmpfs /var/lib/postgresql/data:rw,size=2g -p 127.0.0.1:55432:5432 -e POSTGRES_USER=smh_acceptance -e POSTGRES_PASSWORD=$localPassword -e POSTGRES_DB=smh_chatbot pgvector/pgvector:pg16
docker exec smh-acceptance-ui-pg createdb -U smh_acceptance smh_tenant
docker exec smh-acceptance-ui-pg createdb -U smh_acceptance smh_platform
$dbPassword = [uri]::EscapeDataString($localPassword)
$env:DATABASE_URL = "postgresql+psycopg://smh_acceptance:$dbPassword@127.0.0.1:55432/smh_chatbot"
$env:TENANT_DATABASE_URL = "postgresql+psycopg://smh_acceptance:$dbPassword@127.0.0.1:55432/smh_tenant"
$env:PLATFORM_DATABASE_URL = "postgresql+psycopg://smh_acceptance:$dbPassword@127.0.0.1:55432/smh_platform"
```

Backend, from the backend folder in the isolated source copy (use random local-only secrets of at least 32 characters):

```powershell
$env:ENVIRONMENT = 'development'
$env:AUTH_SECRET = '<random-local-only-secret>'
$env:CHANNEL_ENCRYPTION_KEY = '<random-local-only-secret>'
$env:CHANNEL_ROUTE_SECRET = '<random-local-only-secret>'
$env:CORS_ORIGINS = 'http://127.0.0.1:5174,http://localhost:5174'
$env:ALLOWED_HOSTS = '127.0.0.1,localhost'
$env:REDIS_URL = ''
$env:RATE_LIMIT_ENABLED = 'false'
$env:OTP_DELIVERY_MODE = 'disabled'
$env:RAG_AUTO_REPLY_ENABLED = 'false'
$env:RAG_IMAGE_CATALOG_MATCH_ENABLED = 'false'
$env:SALES_JOURNEY_ENGINE_ENABLED = 'false'
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Frontend, in a second terminal:

```powershell
$env:VITE_API_BASE_URL = 'http://127.0.0.1:8001/api'
npm run dev -- --host 127.0.0.1 --port 5174
Start-Process 'http://127.0.0.1:5174/'
```

The backend startup initializes its configured database, so use only the disposable databases above. Create a synthetic owner account there using `backend/scripts/create_admin.py`; do not use a real staff/customer account. A separate synthetic read-only account is needed to check read-only authorization.

After the browser review, stop the app processes with `Ctrl+C` and stop the disposable DB with `docker stop smh-acceptance-ui-pg` (the `--rm` option removes that temporary container after it stops).

### Manual browser checklist

1. Log in with the synthetic owner and verify session persistence, logout, and that no real shop/customer records appear.
2. Navigate through Inbox, Customer 360, Knowledge Base, Sales Orders, Products/Inventory and Settings; check empty states, loading/error states, back/forward navigation and refresh behavior.
3. Use only synthetic records. Verify no order, payment, appointment, message, handoff, or provider call is created by read-only browsing.
4. Log in separately with a synthetic read-only account; confirm write controls are hidden/disabled and direct API writes are denied.
5. At desktop width, inspect layout, buttons, forms and scroll regions. Repeat at a mobile viewport (for example 390×844); check overflow, clipped dialogs and usable touch targets.
6. Inspect browser console and Network for uncaught errors, failed API calls, CORS failures, repeated requests and any request to a non-local provider.
7. Capture screenshots only after confirming the page contains synthetic data; redact tokens, email addresses and any secrets.
8. Stop the backend/frontend and disposable database after review. Do not run database migrations against any non-disposable environment.

This checklist is prepared, not executed. Prior synthetic HTTP/API smoke from the preceding acceptance is not substituted for visual browser acceptance.

## RAG answer-quality preparation

Prepared `backend/test_data/rag_answer_quality_acceptance_v1.jsonl`: 20 unique synthetic conversations, valid JSONL. SHA-256: `340e70c14bcd7f954650570a6ada9b7c9539d37cb149467017577ea5e97bb386`.

Coverage includes current price/stock, budget filtering, comparison, multi-turn context and context switch, Vietnamese typo normalization, exact/unknown SKU, ambiguous variant clarification, unsupported policy, supported policy, multi-source grounding, cross-tenant isolation, knowledge-base prompt injection, quote without order side effect, out-of-stock handling, compatibility uncertainty, stale KB price, image observation evidence, and read-only service availability.

Every case contains synthetic evidence IDs, an acceptable gold response/action, required claims, prohibited claims, and correctness/groundedness/hallucination criteria. It is an evaluation fixture, not human-approved ground truth and has not been run against an LLM. Record per case: answer correctness, evidence support for every factual claim, unsupported-claim count, hard-error flags (tenant/price/stock/action), latency, token usage and model-call count. Do not call the RAG improved until a provider-approved run is scored against this set and reviewed.

`RAG_ANSWER_QUALITY=NOT_MEASURED`: no provider credential or separate approval was supplied; no model call was made.

## Privacy owner decisions still required

1. Approve the purpose wording and policy version for Sales Journey persistence, or keep that feature disabled.
2. Decide whether single-conversation reply memory may be used when no explicit consent row exists; current code distinguishes this operational context from training/profile signals but permits it absent an opt-out/revocation.
3. Approve memory retention and physical metadata-purge period/SLA. The 30-minute logical read TTL is not proof of physical deletion.
4. Define what to do when consent is revoked during an in-flight model turn: whether to abort before generation, discard generated output, suppress outbound delivery, and how to handle provider data already sent.
5. Approve the applicable consent scope and policy version, plus who is responsible for honoring a revocation across workers and channels.

No policy values were invented and no feature flag was enabled.

## Evidence classification and remaining blockers

- **IMPLEMENTED:** no application source changes in this closure; a 20-case synthetic answer-evaluation fixture and this report were added.
- **TESTED:** disposable PostgreSQL 16 targeted regression and synthetic ACL/race probes; Alembic head inspection; JSONL structure check. Existing backend/frontend full-suite results are recorded baselines, not rerun in this closure.
- **RUNTIME VERIFIED:** targeted database behavior only in disposable PostgreSQL; prior synthetic HTTP/API smoke is recorded separately. No browser runtime or production runtime was exercised.
- **ACCEPTANCE VERIFIED:** incomplete. Consent race is reproduced and open; browser UI, provider-backed answer quality, configured application-role ACL, privacy-owner decisions and staging are unresolved.

Remaining blockers: consent race and owner policy; actual application DB role grants; browser automation/manual UI run; provider-approved answer-quality evaluation; staging validation. Production is not ready.
