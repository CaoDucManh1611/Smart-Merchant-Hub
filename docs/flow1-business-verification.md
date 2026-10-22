# Flow 1 bounded business verification

Canonical checkout: `C:/Users/DUC_STRONG/Projects/Smart-Merchant-Hub`.
User-approved Gate 1 implementation; no commits, migrations, or live provider calls.
Journeys were derived from the requested appointment, order, quotation, and project slice.

## Changes and ownership

- `frontend/src/IndustryModules.vue`: project customer selection is disabled during editing; PATCH omits `customer_id`. POST still includes the numeric customer ID. Existing API contract is preserved.
- `backend/app/api/commercial.py`: quote line edits now persist normalized replacement items as well as recalculated subtotal/tax/total. Previously, the handler computed replacement lines into `changes`, then skipped `items` in its assignment loop, leaving old lines with new amounts.
- New tests: `frontend/tests/business-project-update.test.mjs` and `backend/tests/test_business_workflow_regressions.py`.
- Schemas actually live inside `appointments.py` and `commercial.py`; `backend/app/schemas/industry_modules.py` does not exist. No schema relocation or exports added.
- No edits to appointments, sales, order service, App.vue, onboarding, payments, checkout, routers, models, or exports. Concurrent unrelated checkout changes were left alone.

Scope/callers reviewed: `saveProject` and `editProject`, project create/update routes, `update_quote`, quote total normalization/output, direct business tests, appointment update/conflict helpers, and shared order transition/payment/refund tests. The quote fix affects the existing PATCH handler and its direct callers; it uses the same normalization and money rounding as before.

## TDD evidence

1. Before the frontend edit, `node --test tests/business-project-update.test.mjs` ran from `frontend`: **1 passed, 2 failed**. Failures showed PATCH retained `customer_id` and the customer selector had no disabled binding.
2. Before the backend edit, the combined backend command below yielded **7 passed, 13 failed**. The new quote regression failed because returned/persisted item name was `Old` instead of `New`. Twelve existing order API tests failed at host middleware with `Invalid host header`, before business logic ran.
3. Applied the two-line frontend fix and one-line quote handler fix.
4. Same backend targets, with the container host allowlist explicitly set for TestClient, yielded **20 passed in 9.18s**. The previously failing quote regression passed. No lifecycle production change was needed for the host configuration failures.
5. Frontend project/commerce command yielded **8 passed**. The final focused frontend command below yielded **23 passed**.
6. Existing order row-lock source regression separately yielded **1 passed in 1.23s**.

No checkpoint commits were created, following the user's explicit instruction. This report preserves RED/GREEN evidence.

## Isolation and actual commands

The backend container mounts canonical `backend/app` at `/app/app`, but does not mount `backend/tests`. Tests were copied to `/tmp/flow1-business-tests`:

```powershell
& 'C:/Users/DUC_STRONG/AppData/Local/Programs/DockerDesktop/resources/bin/docker.exe' cp 'C:/Users/DUC_STRONG/Projects/Smart-Merchant-Hub/backend/tests' smart_merchant_20261005_backend:/tmp/flow1-business-tests
& 'C:/Users/DUC_STRONG/AppData/Local/Programs/DockerDesktop/resources/bin/docker.exe' cp 'C:/Users/DUC_STRONG/Projects/Smart-Merchant-Hub/backend/tests/test_business_workflow_regressions.py' smart_merchant_20261005_backend:/tmp/flow1-business-tests/test_business_workflow_regressions.py
```

Final combined backend command (**20 passed**):

```powershell
& 'C:/Users/DUC_STRONG/AppData/Local/Programs/DockerDesktop/resources/bin/docker.exe' exec -e ALLOWED_HOSTS=testserver,localhost -e ENVIRONMENT=test -e DATABASE_URL=sqlite:////tmp/business-legacy.db -e PLATFORM_DATABASE_URL=sqlite:////tmp/business-platform.db -e TENANT_DATABASE_URL=sqlite:////tmp/business-tenant.db -e RUN_POSTGRES_TESTS=0 -e PYTHONPATH=/app -w /tmp smart_merchant_20261005_backend python -m pytest /tmp/flow1-business-tests/test_business_workflow_regressions.py /tmp/flow1-business-tests/test_industry_modules.py /tmp/flow1-business-tests/test_order_lifecycle.py /tmp/flow1-business-tests/test_sales_inventory_lifecycle.py /tmp/flow1-business-tests/test_order_payments.py -q
```

The RED backend command used the same targets/options except `ALLOWED_HOSTS` was absent. Explicit database URLs prevent import-time inheritance of live PostgreSQL settings. Copied `conftest.py` additionally overrides databases into isolated `/tmp/.pytest_tmp` SQLite files before application imports. Individual business fixtures use in-memory SQLite; provider email functions are mocked in the existing industry test. New regression fixtures stub workflow event emission.

Source-relative test setup and command (**1 passed**):

```powershell
& 'C:/Users/DUC_STRONG/AppData/Local/Programs/DockerDesktop/resources/bin/docker.exe' exec smart_merchant_20261005_backend ln -s /app/app /tmp/app
& 'C:/Users/DUC_STRONG/AppData/Local/Programs/DockerDesktop/resources/bin/docker.exe' exec -e ALLOWED_HOSTS=testserver,localhost -e ENVIRONMENT=test -e DATABASE_URL=sqlite:////tmp/business-legacy.db -e PLATFORM_DATABASE_URL=sqlite:////tmp/business-platform.db -e TENANT_DATABASE_URL=sqlite:////tmp/business-tenant.db -e RUN_POSTGRES_TESTS=0 -e PYTHONPATH=/app -w /tmp smart_merchant_20261005_backend python -m pytest /tmp/flow1-business-tests/test_order_service_query.py -q
```

From canonical `frontend` (**23 passed**):

```powershell
node --test tests/business-project-update.test.mjs tests/commerce-operations.test.mjs tests/calendar-utils.test.mjs tests/orders-p1-02.test.mjs
```

Scoped whitespace review (**exit 0**, no errors):

```powershell
git diff --check -- backend/app/api/commercial.py frontend/src/IndustryModules.vue
```

## Guarantees checked

| Guarantee | Evidence |
| --- | --- |
| Project create includes customer; update omits it and preserves form state | New frontend executable save-handler tests |
| Project customer selector is disabled during editing | New frontend template binding regression |
| Edited quote lines persist and match recalculated subtotal, tax, total | New backend regression, database expire/reload |
| Appointment +07:00 update roundtrip returns UTC and keeps duration | New backend regression; existing create roundtrip test |
| Assigned staff overlaps reject with 409; adjacent intervals and another tenant do not conflict | New conflict-boundary regression |
| Completed/cancelled/no-show appointments cannot reopen or reschedule | Three parametrized regressions |
| Partial project dates validate against stored counterpart; nullable start can be cleared | New backend regression |
| Quote tax, accepted conversion replay, terminal quote/project transitions, tenant-scoped reads/writes | Existing industry workflow tests |
| Order transition graph, stock reservations/shipment/cancellation and refunds | Existing order/inventory lifecycle tests |
| Payment replay, overpayment/refund bounds, completion payment requirement and completed-order refunds | Existing order payment tests |
| Order lock query avoids nullable collection joinedload | Existing source regression |

## Failed attempts and limits

- Initial Docker call without sandbox elevation failed to connect to its named pipe; elevated execution worked.
- Initial `/app/tests/...` command: no tests ran, because test files were not mounted.
- First scratch-space batch: collection failed because the source-relative order query test looked for `/tmp/app/services/order_service.py`. The scratch symlink above resolved this; production paths were not changed.
- First runtime batch: **13 failed, 7 passed**, consisting of one intended quote RED and twelve host-middleware failures; final test-only host configuration resolved the latter.
- `npm run build`: **failed**, `'vite' is not recognized as an internal or external command`. Local frontend dependencies are unavailable; no dependency installation was performed.
- No full-suite, coverage, browser rendering/accessibility, PostgreSQL concurrent-lock, lint, or typecheck claim. Frontend checks execute the extracted save handler and inspect the template binding; they do not mount Vue in a browser. Native disabled semantics follow the focused `ui-ux-pro-max` guidance.
- SQLite checks do not prove PostgreSQL concurrency behavior. Build remains unverified until frontend dependencies are available.
- Container scratch tests, SQLite artifacts, and `/tmp/app` symlink remain for reproducibility. No live tenant data or provider state was modified.
