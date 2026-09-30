# CRM P1 Capabilities Finalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the operational Team & Permission, Reports, Knowledge Base/RAG, and AI capabilities on `crm-completion` with auditable tenant-scoped contracts and usable UI states.

**Architecture:** Retain the existing FastAPI/Vue contracts, adding only additive report filters, permission lifecycle actions, and UI orchestration. Database models remain tenant-owned; mutations record audit events, deny overrides take precedence, and background RAG/AI behavior exposes durable state rather than hidden work.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, Vue 3, Vite, pytest, Node test runner.

**Spec:** `docs/superpowers/specs/2026-09-07-crm-completion-gaps-design.md`

## Global Constraints

- Every endpoint reads and writes only records belonging to the active `business_id`.
- Permission denial overrides every role default and any allow override.
- Report filters are optional and backward compatible when omitted.
- RAG failure details are sanitized before persistence or display.
- The AI baseline runs without external provider credentials; all model, experiment, and bandit outputs retain versioned evidence.

---

### Task 1: Permission lifecycle and audit

**Files:**
- Modify: `backend/app/api/team.py`
- Modify: `backend/tests/test_permissions_api.py`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/tests/crm-shell.test.mjs`

**Interfaces:**
- Produces `DELETE /api/team/permissions/{override_id}` returning `204`.
- Produces an `audit_logs` record with `resource_type="permission_override"` for create and delete.

- [ ] **Step 1: Write the failing test**

```python
def test_permission_override_is_audited_and_can_be_removed(self):
    created = self.client.post("/api/team/permissions", headers=self.headers, json={"resource": "orders", "action": "write", "effect": "deny", "role": "agent"})
    self.assertEqual(201, created.status_code)
    removed = self.client.delete(f"/api/team/permissions/{created.json()['id']}", headers=self.headers)
    self.assertEqual(204, removed.status_code)
```

- [ ] **Step 2: Run the focused test and verify it fails because the delete route is absent.**

```powershell
cd backend
$env:PYTHONPATH = "$PWD\.migrationdeps;$PWD"
py -3.12 -m pytest tests/test_permissions_api.py -q
```

- [ ] **Step 3: Implement the minimal delete/audit path and a remove control in Team Settings.**

- [ ] **Step 4: Re-run permission and frontend shell tests.**

### Task 2: Filterable CRM reports

**Files:**
- Modify: `backend/app/api/revenue.py`
- Modify: `backend/app/api/leads.py`
- Modify: `backend/app/api/tickets.py`
- Modify: `backend/tests/test_crm_attribution_pipeline.py`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/tests/crm-shell.test.mjs`

**Interfaces:**
- Adds optional `start_at`, `end_at`, `channel`, `source`, `owner_id`, and `status` query fields only where the underlying report owns that field.
- Existing no-filter responses keep their current JSON fields.

- [ ] **Step 1: Write failing API tests for a date/channel/source-filtered attribution report and an owner/status-filtered pipeline or ticket report.**

```python
filtered = self.client.get("/api/reports/revenue-attribution?model=linear&channel=telegram&source=campaign", headers=headers)
self.assertEqual(200, filtered.status_code)
self.assertEqual(["telegram"], [item["channel"] for item in filtered.json()["items"]])
```

- [ ] **Step 2: Run the focused tests and verify the filter contract fails before the route changes.**

- [ ] **Step 3: Apply each filter to the tenant-scoped query and forward the active UI filters to all report requests.**

- [ ] **Step 4: Re-run report and frontend tests.**

### Task 3: Durable RAG retry observability

**Files:**
- Modify: `backend/app/api/documents.py`
- Modify: `backend/tests/test_rag_operations.py`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/tests/crm-shell.test.mjs`

**Interfaces:**
- Adds `POST /api/documents/runs/{run_id}/retry`, returning the new queued run for the same tenant/document.
- A retry is permitted only for `failed` RAG runs with retained source bytes; sanitization remains unchanged.

- [ ] **Step 1: Write a failing test showing a failed run can create a distinct queued retry and a different tenant gets `404`.**

```python
retry = self.client.post(f"/api/documents/runs/{failed_run_id}/retry", headers=headers)
self.assertEqual(201, retry.status_code)
self.assertEqual("queued", retry.json()["status"])
```

- [ ] **Step 2: Run the focused test and verify the retry route does not exist.**

- [ ] **Step 3: Queue a new `rag.ingest` job through the existing ingestion helper and show retry state/action in the document UI.**

- [ ] **Step 4: Re-run RAG and frontend tests.**

### Task 4: AI Lab operational UI

**Files:**
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/style.css`
- Modify: `frontend/tests/crm-shell.test.mjs`

**Interfaces:**
- Consumes existing `/api/experiments/models`, `/report`, `/bandit/policies`, and `/bandit/select` APIs.
- Shows model version/status/metrics, experiment arm metrics/stop state, and policy version/epsilon/decision output.

- [ ] **Step 1: Write a failing frontend test for visible model metrics, A/B arm report, and bandit policy state in the AI Lab.**

```javascript
assert.match(source, /Model versions/);
assert.match(source, /Bandit policy/);
assert.match(source, /Conversion rate/);
```

- [ ] **Step 2: Run the Node test and verify it fails because the AI Lab has no operational panels.**

- [ ] **Step 3: Add bounded loading/error/empty states and API actions without adding external credentials or automatic production decisions.**

- [ ] **Step 4: Run all frontend tests and inspect the production build.**

### Task 5: Final P1 verification

**Files:**
- Verify: `backend/tests/`
- Verify: `frontend/tests/`
- Verify: `backend/alembic/`

- [ ] **Step 1: Run the complete backend suite.**

```powershell
cd backend
$env:PYTHONPATH = "$PWD\.migrationdeps;$PWD"
py -3.12 -m pytest -q
```

- [ ] **Step 2: Run the full frontend suite and production build.**

```powershell
cd frontend
node --test tests/*.test.mjs
npm run build
```

- [ ] **Step 3: Run Alembic head/current/check and `git diff --check`; report any Docker-only blocker separately.**
