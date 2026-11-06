# Smart Merchant Hub — Final Acceptance Results

Date: 2026-11-05 (Asia/Bangkok)
Workspace: `C:\Users\Administrator\Documents\Codex\2026-09-03\referenced-chatgpt-conversation-this-is-an\work\smart-merchant-hub`
Branch: `codex/rag-rfm-all-updates-20261104`
HEAD: `92ae7e34c532d3d5b331e3c7343dcd9a20375f61`

```text
SOURCE_INTEGRITY=PASS_SAFE_SOURCE_MANIFEST_158_FILES;270_INHERITED_CHANGES_PRESERVED;1_TEST_EXPECTATION_FIX;NO_STAGED_CHANGES
BROWSER_UI=NOT_VERIFIED
POSTGRESQL_RUNTIME=PARTIAL_DISPOSABLE_POSTGRESQL_16_TARGETED_TESTS
TENANT_ISOLATION=PARTIAL_VERIFIED_ON_DISPOSABLE_POSTGRESQL;PRODUCTION_NOT_VERIFIED
CONSENT_RACE=OPEN
RAG_RETRIEVAL=PASS_SYNTHETIC_51_CASES;RETRIEVAL_ONLY
RAG_ANSWER_QUALITY=NOT_MEASURED
LOCAL_DEMO_READY=PARTIAL_SYNTHETIC_HTTP_SMOKE_ONLY;VISUAL_BROWSER_NOT_VERIFIED
STAGING_READY=NO_NOT_VERIFIED
PRODUCTION_READY=NO
EXACT_REMAINING_BLOCKERS=VISUAL_BROWSER_ACCEPTANCE;CONSENT_READ_REVOCATION_RACE;PRIVACY_PURPOSE_AND_RETENTION_APPROVAL;PHYSICAL_EXPIRY_PURGE_EVIDENCE;APPLICATION_DB_ROLE_PRIVILEGES;PROVIDER_BACKED_ANSWER_QUALITY;STAGING_VALIDATION
```

## Scope and source integrity

- Preserved the 270 pre-existing dirty changes. No reset, clean, stash, commit, push, merge, deploy, or production access occurred. Branch and HEAD remained unchanged; the index has no staged paths.
- This acceptance added one narrow test-only correction in `backend/tests/test_tenant_migration_runner.py`: expected tenant migration head updated from stale `20261101_0015` to current `20261104_0017`. No application behavior was changed. The requested report is an additional untracked artifact.
- Final safe-source manifest: `C:\Users\Administrator\AppData\Local\Temp\smh-primary-source-manifest-20261105-final.csv`; 158 source files hashed (87 modified, 71 untracked source files), SHA-256 `b4acb89147e253cd64124d389653fa42bf8943f79f0ff20fdf098c824a905201`. The manifest excludes `.env`, database files, secrets/config credentials, reports, dependency directories, caches, uploads, and backups. It is a hash manifest, not a content snapshot.
- `backend/test.db` remains a pre-existing tracked file; it was not read, copied, or included in any artifact. Its Git status is clean. The temporary PostgreSQL instance used only tmpfs and was stopped after testing; port 55432 is no longer listening.
- Expected final Git status count is 272 entries: 270 inherited entries, one acceptance test change, and this report. Nothing is staged.

## Browser UI acceptance

`BROWSER_UI=NOT_VERIFIED`. Browser automation could not initialize: the Codex browser runtime rejected importing `node:process`. No real-browser login, page navigation, desktop/mobile layout, browser console, or browser network inspection was completed. Prior HTTP smoke results are not treated as browser UI evidence.

## PostgreSQL and database checks

A disposable PostgreSQL 16/pgvector container was used on loopback with tmpfs only; tests ran against scratch code and isolated `*_test` databases/schemas. No production database or credentials were used.

- The 16-file targeted PostgreSQL run reported **258 passed, 1 failed, 3 subtests passed** in 102.65 seconds. The single failure was a stale migration-head assertion, not a migration execution error. Updated the test expectation to current revision `20261104_0017`; reran the migration-runner file: **2 passed**. Reran the PostgreSQL database-boundary file: **2 passed**, including transaction-local `search_path` reset across sessions.
- The targeted set included tenant routing/scoped queries, API tenant isolation, authenticated tenant sessions, conversation memory, Journey privacy, feedback consent, worker blocked state, order/subscription payment behavior, and migration runner. The broad 16-file set was not rerun as a single clean batch after the assertion correction; therefore it is not reported as an all-green PostgreSQL suite.
- An initial run with a 1 GiB tmpfs hit PostgreSQL `DiskFull`; increasing the disposable tmpfs to 2 GiB allowed the 16-file run to complete and produce the results above.
- A separate host-side probe for database-role ACLs did not authenticate to the disposable instance. It created no role/schema/data. Actual application-role privileges, direct PostgreSQL row-lock acceptance, and PostgreSQL consent-revocation race behavior remain `NOT_VERIFIED`.
- PostgreSQL evidence is limited to this disposable test harness. It does not establish production connection-pool behavior, production role grants, or production concurrency safety. No production migration was run.

Raw logs:
- `C:\Users\Administrator\AppData\Local\Temp\smh-final-acceptance-20261105\postgres-targeted-acceptance-final.log`
- `C:\Users\Administrator\AppData\Local\Temp\smh-final-acceptance-20261105\postgres-migration-runner-final.log`
- `C:\Users\Administrator\AppData\Local\Temp\smh-final-acceptance-20261105\postgres-database-boundaries-final.log`
- `C:\Users\Administrator\AppData\Local\Temp\smh-final-acceptance-20261105\postgres-direct-checks.log` (failed host authentication; no DB mutation)

## Existing offline and smoke evidence

- Backend full suite after integration: **2,198 passed, 6 skipped, 37 subtests passed**, exit 0, SQLite; 152.10 seconds. This is the recorded pre-acceptance baseline; only the migration test assertion changed in this acceptance.
- Frontend: **327 passed**, exit 0. Production build passed with an existing large-chunk warning (>500 kB). No frontend source changed in this acceptance.
- Prior synthetic local HTTP/API smoke covered health, login, tenant identity, CRM, knowledge listing, chatbot configuration, and a deterministic conversation with no external provider or order/payment/handoff side effect. Frontend HTTP/proxy smoke also passed. These were not visual browser or provider-backed end-to-end tests.
- Synthetic RAG retrieval benchmark: 51 cases, 30 synthetic documents, 3 synthetic tenants; relevant-case rate@5 1.0, evidence recall@5 0.961538, MRR@5 1.0, empty-result accuracy 12/12, forbidden-evidence hits 0, tenant-isolation violations 0. This is retrieval evidence only.
- No approved model/provider credential was used and no external model was called. Generated-answer correctness, groundedness, hallucination rate, answer latency, and model-call count are `NOT_MEASURED` in this acceptance.
- `SALES_JOURNEY_ENGINE_ENABLED=False` remains the source default. No feature flag was enabled.

## Privacy gate and remaining blockers

- `CONSENT_RACE=OPEN`: prior review identified an in-flight memory read that can overlap consent revocation. Existing tests cover revoke/opt-out read/write blocking and scoped purge, but do not prove cross-worker PostgreSQL race closure.
- Journey persistence requires a non-empty configured purpose and policy version and defaults to requiring consent. Both purpose and version default to blank, so persistence fails closed until configured. The purpose wording/version still requires owner/privacy/legal approval.
- Reply memory is documented in code as single-conversation operational context rather than a profile/training signal. It blocks explicit denial/revocation and fact-extraction opt-out; absence of a consent row is currently allowed. The owner/privacy reviewer must approve whether that purpose and rule are acceptable.
- Reply-memory state has a 30-minute logical TTL enforced during reads. This check did not verify scheduled physical expiry/purge of old message metadata. Retention duration, purge schedule/SLA, and any policy wording remain for the data owner/privacy/legal reviewer to approve; no policy was invented here.
- Production application-role grants, browser UI, staging, production runtime, and provider-backed RAG answer quality remain unverified. The consent race and these evidence gaps prevent production acceptance.

## Evidence classification

- **IMPLEMENTED:** integrated source patch remains present; this task changed only the stale migration test expectation and added this report.
- **TESTED:** prior SQLite/backend/frontend baselines; targeted disposable PostgreSQL runs and focused reruns recorded above; synthetic retrieval benchmark.
- **REVIEWED:** prior Gauss final static review reported 0 P0/P1 on the reviewed integration diff. This acceptance’s test-only expectation adjustment did not alter app code; no new independent review was requested or represented as having occurred.
- **RUNTIME VERIFIED:** prior synthetic HTTP/API smoke only; no visual browser or production runtime verification.
- **ACCEPTANCE VERIFIED:** incomplete for UI, PostgreSQL role/concurrency, answer quality, staging, and production. Do not treat this report as a production PASS.
