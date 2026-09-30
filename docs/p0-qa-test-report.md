# P0 QA test report

**Date:** 2026-09-13
**Branch:** `crm-completion`
**Baseline:** `8fbb3f2` plus the current uncommitted P0 changes
**Environment:** Windows, Docker Compose, PostgreSQL/pgvector 16, Redis 7.4,
FastAPI backend and Vite/Vue frontend

## Release assessment

**Conditional pass.** All local automated, integration and restore-rehearsal
gates passed. Production release is still conditional on controlled live
callbacks from Facebook, Instagram, Telegram and Zalo, plus one real SMTP OTP
to an explicitly approved test mailbox.

No live OTP email was sent during this run. Provider credentials and customer
payloads were not printed in test output.

## Test execution summary

| Suite | Result | Evidence |
|---|---:|---|
| Backend full regression | PASS | 432 passed, 0 failed, 0 errors, 0 skipped |
| Frontend regression | PASS | 97 passed, 0 failed |
| Frontend production build | PASS | Vite build completed; 20 modules transformed |
| Docker runtime | PASS | backend, worker, frontend, PostgreSQL and Redis healthy |
| PostgreSQL restore rehearsal | PASS | isolated restore, migration and drift check completed |
| Redis shared limiter smoke | PASS | two instances shared state: allow, allow, reject |
| Operational endpoints | PASS | `/health/details` OK, `/metrics` 200, 0 active alerts |

Two non-blocking warnings remain: one deprecated `datetime.utcnow()` call in
an older follow-up test and the upstream deprecation of
`google.generativeai`. Neither caused a P0 test failure; migration to
`google.genai` should be scheduled separately.

## P0 test matrix

| ID | Area | Test case | Expected result | Status |
|---|---|---|---|---|
| DB-01 | Backup | Read `crm16.dump` using `pg_restore --list` | Archive is readable | PASS |
| DB-02 | Restore | Restore dump into isolated temporary PostgreSQL database | Restore exits successfully | PASS |
| DB-03 | Migration | Run `alembic upgrade head` then `alembic check` | No schema drift | PASS |
| DB-04 | Data | Count restored tables/conversations/messages | 82 / 8 / 713 | PASS |
| DB-05 | Safety | Drop only the named rehearsal database | Temporary database count returns 0 | PASS |
| WH-01 | Meta | Valid Facebook and Instagram raw-body HMAC | Accepted and tenant-bound | PASS |
| WH-02 | Telegram | Valid configured webhook secret header | Accepted and tenant-bound | PASS |
| WH-03 | Zalo | Valid Bot secret and OA signature | Accepted and tenant-bound | PASS |
| WH-04 | Tampering | Invalid signature/secret for all four channels | HTTP 401; no message/event written | PASS |
| WH-05 | Replay | Deliver the same normalized event again | No duplicate event/message | PASS |
| WH-06 | Tenant | Resolve channel account to its owning business | No cross-tenant persistence | PASS |
| RL-01 | Redis | Redis health check | PONG/healthy | PASS |
| RL-02 | Shared limit | Consume one key through two limiter instances | Third request rejected globally | PASS |
| RL-03 | HTTP contract | Exceed configured request count | HTTP 429 with limit/reset/retry headers | PASS |
| RL-04 | Dependency failure | Redis connection fails | API fails closed with 503; health stays reachable | PASS |
| RL-05 | Proxy security | Spoof `X-Forwarded-For` while proxy is untrusted | Rate limit cannot be bypassed | PASS |
| SEC-01 | Secret file | Load known scalar keys from mounted JSON | Known keys loaded; unknown keys ignored | PASS |
| SEC-02 | Secret file | Invalid JSON/non-scalar/unknown mode | Safe explicit error; value not leaked | PASS |
| SEC-03 | Rotation | Run encryption-key rotation without `--confirm` | Database changes roll back | PASS |
| SEC-04 | Rotation | Commit rotation | Channel/MFA/contact data re-encrypted; pending OTP expired | PASS |
| SEC-05 | Key pool | Inspect AI key pool status | Counts only; raw keys absent | PASS |
| OTP-01 | SMTP | Build and send through mocked authenticated SMTP | TLS/login/message contract correct | PASS |
| OTP-02 | Twilio | Send through mocked provider | Correct authenticated request | PASS |
| OTP-03 | Production safety | Use `in_chat` in production | Rejected before delivery | PASS |
| OTP-04 | Channel safety | Use SMTP for SMS or Twilio for email | Rejected before network I/O | PASS |
| OTP-05 | Live delivery | Send one OTP to an approved staging mailbox | Provider confirms delivery | BLOCKED |
| BK-01 | Backup script | `pg_restore` returns non-zero | Script fails; never prints success | PASS |
| BK-02 | Backup script | `pg_dump` returns non-zero | Script fails; never prints success | PASS |
| BK-03 | Backup script | Native command returns zero | Success printed only after validation | PASS |
| OBS-01 | Database alert | Database check fails | Critical alert without connection details | PASS |
| OBS-02 | Queue alert | Pending/failed jobs cross threshold | Backlog/failed-job alerts fire | PASS |
| OBS-03 | Provider alert | Circuit is open | Provider critical alert fires | PASS |
| OBS-04 | AI cost alert | Period cost reaches threshold | Cost warning fires at boundary | PASS |
| OBS-05 | Metrics privacy | Render Prometheus payload | Fixed low-cardinality metrics; no secrets | PASS |

## Defects found and handled

### QA-001 — backup verification could report false success

`pg_dump` and `pg_restore` native exit codes were not enforced consistently.
The script now throws on every non-zero exit code. Positive and negative
regression tests pass.

### QA-002 — pytest failed on the protected Windows Temp directory

Two RAG logger tests could not create `tmp_path`, creating false test errors.
Pytest now uses a repository-local ignored base-temp directory and works when
invoked from either the repository root or `backend`.

### QA-003 — background test work could inherit Docker database hostname

Some webhook tests could start background work after their request-scoped
SQLite fixture ended, then try to resolve the Docker-only hostname `db` from
Windows. The shared test bootstrap now points global application sessions to
an isolated SQLite database and disables automatic RAG work by default. A
plain full regression now completes with 432 passes and no errors.

## Remaining production gates

1. Send one controlled live callback from each provider dashboard and verify
   one `channel_events` row plus one message per delivery.
2. Approve an exact staging mailbox, send one real OTP, and verify provider
   delivery without copying the code or address into logs.
3. Deploy with `RATE_LIMIT_ENABLED=true`, `RATE_LIMIT_BACKEND=redis` (or a
   trusted shared proxy) and the production HTTPS/secret-manager settings.
