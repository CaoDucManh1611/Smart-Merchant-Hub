# CRM Operations: attribution, pipeline, reporting and permissions

## Goal

Close the CRM operations gaps around revenue attribution, lead conversion/activity, reporting dimensions and granular team permissions without changing existing Customer 360 or order contracts.

## Scope and order

1. Add tenant-scoped attribution and conversion persistence.
2. Add lead activities and a lead-to-sales-order conversion endpoint.
3. Extend reports with attribution, funnel and SLA dimensions.
4. Add permission overrides and route all write checks through one evaluator.
5. Add UI views only after API contracts and tests are stable.

## Implementation tasks

### Data and migrations

- Add `revenue_touchpoints`, `revenue_attributions`, and `lead_conversions` models with foreign keys, tenant keys, indexes on business/time/order/lead, decimal amounts, and uniqueness for an order/touchpoint/model allocation.
- Add a permission override model keyed by business/resource/action/effect, with a unique constraint and audit fields.
- Create one Alembic migration after the current head; make downgrade remove only these tables and indexes.

### Service and API

- Implement an attribution service that derives conversation/channel touchpoints, supports first/last/linear/time-decay/manual models, and is idempotent per order/model version.
- Add endpoints to preview/recalculate attribution and list order/lead touchpoints; validate every referenced customer, conversation, lead and order in the active tenant.
- Add lead activity CRUD and `POST /leads/{id}/convert` that creates an immutable conversion link and prevents duplicate conversion unless explicitly reversed by an admin path.
- Extend reports with date/channel/source/owner/status/model filters while preserving `revenue-by-channel` response fields.
- Add permission override CRUD, effective-policy inspection, and shared `can(resource, action)` evaluation. Deny overrides win; owner/admin defaults remain compatible.

### Frontend

- Add report cards/table for raw versus attributed revenue and lead conversion funnel.
- Add lead activity timeline and conversion action with loading, conflict and empty states.
- Add a team permissions matrix under Team/Settings using the existing Smart Merchant Hub visual language.

## Tests first

- New backend tests: tenant isolation, attribution math/idempotency, conversion conflict, activity ordering, report filters, deny-overrides-grant, and owner/admin/agent/viewer compatibility.
- Update existing report/team tests only for additive response fields.
- New frontend tests cover report filters, conversion error state, and permission matrix interactions.

## Verification

```powershell
cd backend
$env:PYTHONPATH = "$PWD\.migrationdeps;$PWD"
py -3.12 -m pytest tests/test_revenue_attribution_api.py tests/test_lead_pipeline_api.py tests/test_reports_api.py tests/test_permissions_api.py -q
cd ..\frontend
node --test tests/revenue-attribution.test.mjs tests/lead-pipeline.test.mjs tests/permissions.test.mjs
```
