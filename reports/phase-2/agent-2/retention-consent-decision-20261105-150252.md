# Smart Merchant Hub Sales Journey retention and consent decision points

_Policy review - no deletion or production data access performed - 2026-11-05 15:02 +07:00._

## Existing policy components

| Component | Current behavior | Gap for Sales Journey state |
|---|---|---|
| `CustomerConsent` | Tracks purpose, policy version, status, grant/revoke timestamps and evidence | No journey-state purpose is defined |
| Personalization revoke | Scrubs derived facts, interactions, profiles and related recommendation state | Does not clear journey state from `Message.metadata_` or `CrmJob.payload` |
| Privacy anonymize/delete | Clears message content, raw payload and `Message.metadata_` for the lifecycle operation | This is a separate admin lifecycle operation, not a personalization-revocation hook |
| `DATA_RETENTION_DAYS` | Global retention setting defaults to 365 days | No explicit journey metadata owner or cleanup job is tied to it |
| Journey TTL | 30-minute read freshness check | Read invalidation is not physical deletion |
| CRM job | `CrmJob.payload` is tenant-scoped JSON | Collection metadata can remain in jobs unless explicitly scrubbed |

## Policy decisions required

These decisions must be made by the privacy/product owner; Agent 2 must not infer them:

1. Is the journey state strictly necessary service context, or is it personalization, marketing/follow-up, or learning data?
2. Which consent purpose and policy version, if any, authorize durable journey state?
3. What is the physical retention period for `Message.metadata_` and `CrmJob.payload` journey envelopes?
4. Does revocation invalidate only future use, or also require immediate removal from already-written metadata and pending jobs?
5. Which owner performs purge/cleanup, reports counts, retries safely and writes a PII-free audit event?
6. What happens when a purge is temporarily unavailable: block use, ignore state, or retain until a controlled lifecycle job succeeds?

Until these are answered, the correct status is:

```text
RETENTION POLICY: POLICY DECISION REQUIRED
CONSENT OWNER: UNASSIGNED FOR JOURNEY METADATA
TTL = PHYSICAL DELETION: FALSE
```

## Safe implementation direction after policy approval

- Reuse the existing tenant-scoped privacy lifecycle owner rather than creating an untracked side channel.
- Add purpose/version checks before loading journey state for any purpose beyond the current reply.
- Scrub only the journey keys from `Message.metadata_` and `CrmJob.payload` when policy requires it; do not delete messages, orders or jobs in this checkpoint.
- Treat failed/pending/undelivered jobs as a separate retention case and do not resume state from an unconfirmed outbound message.
- Keep audits to counts, identifiers needed for scope, policy version and status; never include message content, contact fields or serialized slot values.

**RETENTION/CONSENT: EXISTING GENERAL CONTROLS PRESENT; JOURNEY-SPECIFIC OWNER AND POLICY NOT DECIDED.**
