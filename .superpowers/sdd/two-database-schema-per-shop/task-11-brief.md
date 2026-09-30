# Task 11 — Chuyển workflow, ticket, notification, privacy và jobs

## Files
- Modify `backend/app/api/workflows.py`, `tickets.py`, `notifications.py`, `privacy.py`.
- Modify `backend/app/services/crm_job_worker.py`, `backend/app/scripts/crm_job_worker.py`.
- Modify `backend/app/models/crm_job.py`, `workflow.py`, `ticket.py`.
- Create `backend/tests/test_tenant_worker_routing.py`.

## Interface
```python
@dataclass(frozen=True)
class TenantJobEnvelope:
    business_id: int
    schema_name: str
    job_id: int
```

## Required work
- Test workers re-resolve an active registry entry from `business_id`, reject forged schema names, and cannot process a job from a disabled/migrating shop.
- Add lifecycle tests proving export/delete/anonymize affect only one schema and audit the request in the right scope.
- Move operational models/services to tenant DB; place only queue dispatch metadata required for global scheduling in platform/Redis.
- Ensure every retry restores tenant context and clears it on completion/error.
- Run `pytest -q tests/test_tenant_worker_routing.py tests/test_crm_job_worker.py tests/test_platform_quality.py`.
- Commit `refactor: route tenant operations and workers by schema`.

## Global constraints
Server-generated schemas; transaction-local search_path; platform/queue metadata cannot contain tenant content; TDD required. Registry semantics must be compatible with the control-plane plan and later Task 12 routing.

