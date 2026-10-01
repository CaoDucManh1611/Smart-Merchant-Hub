# CRM Customer Operations delivery plan

Branch: `feat/crm-customer-operations`

## Baseline

The repository already contains the core customer-operation flows: tenant-scoped
Customer 360, duplicate merge/undo, consent evidence, conversation assignment,
priority and outcomes, internal notes, ticket SLA, workflows and run history,
API-backed work queue, and repeat-safe CSV preview/import/export.

The implementation therefore preserves those flows and closes only the gaps
confirmed in the current code.

## Delivery phases

1. **Roles and permissions**
   - Add explicit sales and customer-support roles while retaining legacy role aliases.
   - Give both operational read/write access, but keep team, audit and permission
     management restricted to owners/admins.
   - Expose the roles consistently in the Vietnamese/English team UI.
2. **Proactive care by customer segment**
   - Schedule a message for members of a saved tenant-scoped segment.
   - Reuse existing consent, 24-hour frequency cap, durable job queue and
     idempotency logic.
   - Skip customers without a conversation, with bot automation paused, or without
     the required consent; return clear counts to the UI.
3. **End-to-end regression**
   - Verify assignment/handoff, Customer 360 merge/history/consent, workflow runs,
     work-queue navigation and CSV import/export through existing tests.
   - Add focused permission, idempotency and tenant-isolation tests for the new gaps.
4. **UI and release gate**
   - Verify Vietnamese/English copy, keyboard labels, loading/error/empty states and
     responsive behavior.
   - Run frontend tests/build, backend compile/tests and CI before handoff.

## Acceptance criteria

- Owners/admins, sales staff, support staff and automation actors are represented
  without weakening administrative boundaries.
- Segment campaigns never cross shops, never create duplicate follow-ups on retry,
  and honor consent/frequency rules.
- Existing customer-operation APIs remain backward compatible and all applicable
  automated checks pass.
