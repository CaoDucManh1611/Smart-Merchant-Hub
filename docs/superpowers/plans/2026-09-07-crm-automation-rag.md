# CRM Automation and RAG operations

## Goal

Make SLA and workflow execution durable and make RAG ingestion/reindex observable and retryable, while keeping existing manual dispatch endpoints and timeline behavior compatible.

## Implementation tasks

### Durable jobs

- Add `crm_jobs` with tenant, kind, JSON payload, status, attempts, run time, lock time, last error, idempotency key, created/updated timestamps, and indexes for due jobs.
- Implement a transaction-safe claim/complete/fail service with bounded exponential backoff and idempotency.
- Add a dispatcher command and keep the HTTP dispatch endpoint as a development/smoke trigger; never expose credentials or message bodies in errors.

### SLA and workflows

- Enqueue SLA checks when tickets are created/updated and schedule escalation jobs at due time.
- Route scheduled workflow runs through jobs, preserving `workflow_runs` as business history and existing run/dispatch response shapes.
- Add retry/error state and notification/audit records for failed actions; keep supported actions tenant-scoped.

### RAG

- Add durable RAG run/job records with phase, provider, document IDs, chunk count, retry state and sanitized error metadata.
- Replace unbounded request-spawned ingestion/reindex threads with enqueue-and-dispatch behavior while retaining JSONL diagnostics.
- Keep hybrid vector/lexical retrieval, citations and existing document endpoints; add run status and retry endpoints.

### Frontend

- Add workflow/SLA job status and RAG indexing status panels with polling, retry and failure states.
- Preserve current inbox, Customer 360 and document UI contracts; do not reintroduce legacy food branding.

## Tests first

- Backend tests for job claim races, idempotency, retry/backoff, tenant isolation, SLA escalation, workflow dispatch compatibility, RAG status/retry and sanitized errors.
- Frontend tests for pending/success/failure/retry states.
- Add a disposable PostgreSQL migration test covering the new job/RAG tables.

## Verification

```powershell
cd backend
$env:PYTHONPATH = "$PWD\.migrationdeps;$PWD"
py -3.12 -m pytest tests/test_crm_jobs.py tests/test_workflows_api.py tests/test_ticket_sla_api.py tests/test_rag_api.py -q
```
