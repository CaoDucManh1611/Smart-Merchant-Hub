# P1 QA and business acceptance report

**Date:** 2026-09-13
**Branch:** `crm-completion`
**Environment:** Docker Compose, PostgreSQL 16/pgvector, Redis, backend,
worker and Vue frontend
**Scope:** P1 SaaS foundation and P1 product differentiators

## Release assessment

**PASS for local/staging acceptance.** The automated regression, production
frontend build, database migration, tenant RLS probe and runtime health checks
all passed. Existing restored CRM data remained at 8 conversations and 713
messages.

Production activation remains conditional on operator-owned credentials and
infrastructure: a non-superuser application database role, a real payment
provider webhook, real channel credentials and production monitoring/secret
manager destinations. These cannot be certified by fixture credentials.

## Test evidence

| Gate | Result |
|---|---:|
| Backend unit, API, integration and business regression | **450 passed** |
| Frontend behavior regression | **100 passed** |
| Frontend production build | **PASS** |
| Python compile check | **PASS** |
| Git whitespace/error check | **PASS** |
| Docker runtime | **5/5 healthy** |
| Backend health endpoints | **HTTP 200** |
| Frontend and public plan catalog | **HTTP 200** |
| Alembic head | `20260919_0043` |
| PostgreSQL tenant RLS policies | **59** |
| Non-owner RLS probe with an unknown tenant | **0 rows visible** |
| Restored data after deployment | **8 conversations / 713 messages** |

## P1 SaaS test matrix

| ID | Area | Business case and expected result | Status |
|---|---|---|---:|
| ONB-01 | Plan catalog | Seed and list Starter/Growth/Pro idempotently | PASS |
| ONB-02 | Shop creation | Create tenant, owner, active free subscription and tenant JWT atomically | PASS |
| ONB-03 | Paid onboarding | Paid plan starts pending; setup is blocked until payment is active | PASS |
| ONB-04 | Input validation | Reject malformed owner email, duplicate email and duplicate slug | PASS |
| ONB-05 | Tenant identity | JWT `business_id` and role match current database membership | PASS |
| ONB-06 | Channel setup | Connect supported channel within entitlement and audit the action | PASS |
| ONB-07 | Secret safety | Encrypt approved channel secrets and recursively remove nested credentials from persisted config and responses | PASS |
| ONB-08 | Product import | Import new SKU, update an existing SKU case-insensitively and reject duplicate input SKU | PASS |
| ONB-09 | Inventory integrity | Re-import creates a reconciliation stock movement and cannot reduce stock below reserved quantity | PASS |
| CP-01 | Shop control | Platform admin can list, inspect, suspend and reactivate shops | PASS |
| CP-02 | Roles | Owner/admin/member permission boundaries are tenant-scoped | PASS |
| CP-03 | Subscription | Plan, subscription state and validity window govern access | PASS |
| CP-04 | Payment idempotency | Exact replay is safe; mismatched payload or illegal state regression returns conflict | PASS |
| CP-05 | Payment lifecycle | Pending to paid activates subscription; paid to refunded is auditable | PASS |
| CP-06 | Provider diagnostics | Errors are classified without exposing raw provider secrets or payloads | PASS |
| CP-07 | Privacy lifecycle | Platform admin can request export, anonymization and deletion with audit trail | PASS |
| ENT-01 | Entitlements | Staff, channel, document, RAG, AI call and AI cost limits resolve from the active plan | PASS |
| ENT-02 | Exact boundary | Allow up to the limit and reject the first unit over the limit | PASS |
| ENT-03 | Warning | Emit near-quota warning before the hard limit | PASS |
| ENT-04 | Idempotency | Same reservation key replays safely; key reuse with a different resource/amount fails | PASS |
| ENT-05 | Reactivation | Deactivate releases staff/channel capacity; reactivation reserves it again | PASS |
| ENT-06 | Concurrency | Tenant row lock serializes first-use reservations as well as existing usage rows | PASS |
| TEN-01 | Header spoofing | Client cannot switch tenant by supplying a different header | PASS |
| TEN-02 | JWT/session | Tenant and role context flows from signed session through API authorization | PASS |
| TEN-03 | Database defense | RLS uses `app.business_id`; missing/unknown tenant context exposes no tenant rows | PASS |
| TEN-04 | Platform context | Cross-tenant platform operations require explicit platform-admin context and audit | PASS |

## P1 differentiator test matrix

| ID | Area | Business case and expected result | Status |
|---|---|---|---:|
| REV-01 | Revenue | Draft/cancelled orders do not inflate revenue; recognized lifecycle states do | PASS |
| REV-02 | Chat conversion | Measure chatbot-started orders and draft-to-confirmed conversion | PASS |
| REV-03 | Recovered revenue | Attribute confirmed orders after a sent abandoned-cart follow-up | PASS |
| REV-04 | Automation KPI | Expose bot resolution rate without mixing manual CRM orders | PASS |
| GAI-01 | Grounded answer | Product price and stock come from database/tool output, not model invention | PASS |
| GAI-02 | Policy RAG | Timeline exposes safe RAG document IDs used by a response | PASS |
| GAI-03 | Order tools | Order/draft/cancel flows preserve tenant and idempotency constraints | PASS |
| COMBO-01 | Combo quote | Return component prices, combo total and calculated saving/difference | PASS |
| COMBO-02 | Availability | Never recommend unavailable stock as purchasable | PASS |
| COMBO-03 | Alternative | If combo/component is unavailable, suggest only grounded in-stock alternatives | PASS |
| PRO-01 | Abandoned cart | Schedule one durable follow-up, dispatch idempotently and cancel when no longer eligible | PASS |
| PRO-02 | Win-back | Schedule a monthly inactive-customer follow-up only for prior buyers | PASS |
| PRO-03 | SLA warning | Notify before SLA deadline and again only when actually overdue | PASS |
| PRO-04 | Stale jobs | Rescheduled/resolved tickets make old SLA jobs no-op | PASS |
| PRO-05 | Human takeover | Proactive bot follow-up is skipped while staff owns the conversation | PASS |
| XAI-01 | Tool evidence | Customer 360 shows which safe tool was used | PASS |
| XAI-02 | Handoff evidence | Customer 360 shows the reason for handoff/escalation | PASS |
| XAI-03 | Data minimization | Arguments, credentials and secret metadata never appear in explainability UI | PASS |
| C360-01 | Omnichannel identity | Reuse a customer by normalized contact identity instead of duplicating per channel | PASS |
| C360-02 | Tenant isolation | Same external identity in another tenant cannot merge across businesses | PASS |
| C360-03 | Merge safety | Merge is auditable and reversible; canonical profile/timeline remains intact | PASS |

## Defects found and fixed during P1 QA

1. Product re-import matched SKU case-sensitively and changed stock without a
   ledger entry. Matching, reserved-stock validation and reconciliation
   movements were added.
2. Nested channel configuration could retain credential-like keys. Recursive
   redaction and an explicit encrypted-secret allowlist were added.
3. Reconnecting a channel and reactivating a staff member did not reserve quota
   correctly. Capacity release/reservation now follows active-state transitions.
4. A quota idempotency key could be reused for another resource or amount, and
   first-use concurrent reservations had no row to lock. Collision validation
   and a per-tenant transaction lock were added.
5. Paid-plan onboarding could continue while its subscription was pending.
   Setup now requires an active, in-window subscription.
6. Payment callbacks accepted conflicting replay/state regression. A strict,
   auditable payment state machine and identity validation were added.
7. Provider diagnostics exposed an unhelpful type and risked raw details.
   Safe error classification and redacted output were added.
8. SLA automation notified only after breach. Pre-deadline warning, overdue
   notification and stale-job protection were added.
9. Proactive CRM lacked inactive-customer win-back scheduling. A tenant-safe,
   monthly idempotent scheduler was added.
10. Combo failures lacked grounded alternatives. In-stock product suggestions
    now come from the tenant product database.
11. Revenue reports counted draft/cancelled orders. Revenue now uses recognized
    order lifecycle states while order counts still represent operational load.
12. Conversation-to-revenue and explainability evidence existed only partially.
    Recovered revenue, bot resolution, tool/RAG/handoff evidence and dashboard
    cards were completed.

## Tester conclusion

The implemented P1 behavior is internally consistent across API, database,
worker and frontend, and is safe to hand to staging/UAT. Do not label a public
production release fully certified until the remaining credential-owned gates
above are executed in the real deployment environment.
