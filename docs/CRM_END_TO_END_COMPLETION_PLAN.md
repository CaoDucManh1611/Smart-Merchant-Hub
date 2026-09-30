# CRM end-to-end completion plan and verification

Reviewed: 2026-09-30
Branch: `codex/crm-end-to-end-completion`
Repository: `C:\Users\DUC_STRONG\Smart-Merchant-Hub-full-stack-ready`

This is the current acceptance record for the nine workstreams. “Verified” means
covered by the listed automated test, disposable-database rehearsal, or browser
observation; it does not imply live provider or production readiness.

## Execution status

| # | Workstream | Status and evidence |
| --- | --- | --- |
| 1 | Preserve current code and establish a baseline | Implemented changes remain on the existing feature branch and are uncommitted. Existing working-tree changes were preserved. Final backend/frontend gates below pass. |
| 2 | Permissions, tenant boundaries, and state contracts | API and model boundaries are tenant-scoped. Two tenant schemas upgraded independently; search-path isolation passed. The two-shop CRM test verifies a shop cannot fetch the other shop’s order, tenant-filtered reports, and tenant-filtered RAG retrieval. |
| 3 | Channel and RAG reliability | Dedupe/replay, safe outbound idempotency/retry, media typing, document validation/status/retry/delete/deduplication, cited answers, no-context refusal, staff handoff, and content-minimizing logs have implementation and regression coverage. Facebook, Instagram, Telegram, Zalo, and the existing TikTok bridge were tested with fixtures/mocks only. No real provider message or token was used. |
| 4 | Customer operations | Customer identity/merge, contacts and consent, follow-up limits/status, staff assignment/outcomes, work queue, and preview-first CSV import/export have API/UI coverage. Current authenticated screens were not re-opened in this pass. |
| 5 | Commerce and analytics | Existing order/payment/refund/inventory, appointment, quote/project/invoice, and report workflows have regression coverage. The new two-shop flow created and advanced a synthetic order, recorded payment, checked reports, and proved shop separation. No Shopee data was included. |
| 6 | Vietnamese/English, responsive, dark mode, accessibility | Frontend suite passes 191 tests, including locale and responsive/layout assertions. In the current browser pass, the sign-in page had no horizontal overflow at 375×812, 768×900, or 1440×900; the 1440 px console had no errors. This was an unauthenticated sign-in page check. CRM/RAG screens were not visually rechecked in this pass; earlier authenticated checks are recorded in `crm-ui-qa.md`. |
| 7 | Synthetic two-shop data and end-to-end | `backend/tests/test_crm_two_shop_e2e.py` passes with isolated SQLite data; tenant-schema migration and search-path checks pass separately on PostgreSQL 16. Fixtures are created inside tests and removed by teardown. |
| 8 | Migrations and backup/restore | PostgreSQL 16 disposable database passed upgrade, downgrade to `20260926_0007`, and re-upgrade to `20260930_0009`. A custom-format dump restored into a separate empty database with revision `20260930_0009`, all 85 tenant tables, and the synthetic customer row intact. Three Windows PowerShell tests for `backup-verify.ps1` passed; tenant script contract tests passed in the backend suite. The actual tenant PowerShell scripts were not run against PostgreSQL because native PostgreSQL client tools are not installed on the Windows host. The active application database was not used. |
| 9 | Regression, build, documentation, handoff | Backend: 683 passed, 5 environment-gated skips in the standard Linux suite; the two PostgreSQL-only cases and three PowerShell cases were run separately and passed. Frontend: 191 passed. Vite production build passed. Docs are updated below. No screenshot PNG was saved as a repository artifact. |

## Remaining acceptance gates

- Sign in to the running local application and recheck the latest authenticated
  CRM/RAG screens after the current UI changes. The browser was at the sign-in
  page during this pass, so no logged-in visual claim is made here.
- Exercise Facebook and Instagram callbacks, token refresh, inbound delivery,
  and outbound delivery with shop-owned sandbox credentials. Current evidence
  is mock/fixture coverage only, as requested while those integrations are in
  progress. Telegram and Zalo also have no live-delivery claim; TikTok’s bridge
  was not rebuilt.
- Repeat database backup/restore on the exact PostgreSQL major version used by
  the eventual deployment. The isolated rehearsal used PostgreSQL 16; an older
  PostgreSQL 17 rehearsal is retained in the runbook as historical evidence.
- If release policy requires PNG files, capture authenticated screen artifacts
  after sign-in. The in-app browser’s current screenshot was session-only.

The code and mock workflows are ready for local integration testing. Live
provider and deployment-specific acceptance remain external gates; therefore
this plan is not marked “100% production verified.”

## Commands and focused evidence

```powershell
cd backend
python -m pytest -q tests

cd ..\frontend
npm run test
npm run build
```

Focused additions:

- `backend/tests/test_crm_two_shop_e2e.py`
- `backend/tests/test_tenant_migration_runner.py`
- `backend/tests/test_reports_api.py`
- `docs/channel-ai-reliability.md`
- `docs/runbooks/tenant-backup-restore.md`
