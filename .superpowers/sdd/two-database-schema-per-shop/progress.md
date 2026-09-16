# SDD ledger — plan: docs/superpowers/plans/2026-09-15-two-database-schema-per-shop.md

Branch: feat/saas-tenant-channels (created from crm-completion at 18019f8)

Scope owned by this branch: Tasks 8, 9, 10, 11, 12, 14, plus tenant load-test coverage for webhook/RAG/worker.

Preflight rulings:
- Ruling: user explicitly assigned this work to feat/saas-tenant-channels, so this branch is used directly rather than creating an extra worktree. Cost if wrong: branch-local commits may need to be cherry-picked into another worktree.
- Ruling: Task 8 depends on the Task 6 `get_tenant_db` interface, but Task 6 is being developed on another branch and is not present here. This branch must not modify Task 5-7 auth/platform-owned files. Implement tenant-domain/session seams so they are schema-bound and can adopt the canonical Task 6 dependency on merge; do not reintroduce shared-RLS/global credential fallbacks. Cost if wrong: a small integration patch may be needed after the Task 6 branch lands.

Preflight overlap scan:
| Tasks | Shared surface | Finding |
|---|---|---|
| 8 ↔ 12 | channel_service and channel ownership | Task 8 moves channel data into tenant session; Task 12 adds platform routing before opening tenant session. Keep route metadata platform-only and channel/token rows tenant-only. |
| 9 ↔ 10 | chatbot/RAG product lookup | Commerce product/order data is tenant-local; RAG may reference products only through the same tenant session. |
| 10 ↔ 11 | worker job context | RAG ingestion jobs and generic CRM jobs must carry business_id/schema routing metadata without embedding tenant content globally. |
| 11 ↔ 12 | webhook-to-worker handoff | Provider route resolves business/schema first; queued jobs re-resolve registry and reject forged/inactive routing. |
| 12 ↔ 14 | channel routes during cutover | Migration/cutover must switch routing atomically and preserve rollback without leaking tokens into platform DB. |
| 8 | internal consistency | Requires identical IDs across schemas and schema-bound Session. |
| 9 | internal consistency | Requires schema-local SKU/order/idempotency and cancellation lookup. |
| 10 | internal consistency | Requires schema-local documents/vectors/settings and sanitized platform aggregates. |
| 11 | internal consistency | Requires re-resolved worker routing and tenant-only privacy lifecycle. |
| 12 | internal consistency | Requires normalized 4-provider onboarding plus hashed platform routes and encrypted tenant tokens. |
| 14 | internal consistency | Requires dry-run/copy/checksum/cutover/rollback tooling with no content in reports. |

Post-merge reconciliation (2026-09-16):

| Source | Tasks represented after merge | Evidence |
|---|---|---|
| Shared baseline before the branch split | 1, 2, 3, 4 | Two-database settings, independent bases/sessions, platform schema and tenant migration runner are present. |
| `feat/saas-platform-control-tested` | 5, 6, 7, 13, 15, platform portions of 16/19 | Provisioning lifecycle, authenticated shop binding, metadata-only platform APIs, scoped support access, backup/restore scripts and platform observability were merged. |
| `feat/saas-tenant-channels` | 8, 9, 10, 11, 12, 14, tenant portions of 16/19 | Tenant CRM/commerce/RAG/jobs/channels, pilot migration tooling and tenant load contracts remain in this branch. |

The task split covers every Task 1-16 in the implementation plan. The plan's
historical checkboxes are not used as proof of completion because several
red-phase steps intentionally remain unchecked. Verification after resolving
the branch integration conflicts: backend `537 passed, 2 skipped`; frontend
`110 passed`; frontend production build and Python compileall passed. The two
skipped PostgreSQL-only checks and Docker release smoke remain environment
gates and must be rerun before a production cutover.
