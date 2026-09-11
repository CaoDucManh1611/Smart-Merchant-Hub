# CRM Completion Follow-ups Design

## Scope

This follow-up completes the CRM capabilities requested after the SaaS security
baseline. It intentionally excludes building a standalone delivery-management
module. It keeps logistics integration-ready by storing shipment references and
status on sales orders, while customer care remains the primary workflow.

## Goals

1. Make LLM and embedding calls resilient to a pool of five configured API keys.
2. Make customer-care actions reachable from the inbox and Customer 360 in at
   most three user actions.
3. Add tenant-safe logistics metadata to sales orders without implementing a
   carrier marketplace or outbound webhook system.
4. Prepare a repeatable release checklist for next week's CRM rollout.

## Non-goals

- No standalone delivery or warehouse-routing module.
- No automatic external carrier booking.
- No outbound webhooks in this workstream.
- No raw API key values in logs, responses, audit metadata, or the repository.

## Architecture

The key pool is a small in-process service shared by the LLM and embedding
callers. It parses comma-separated environment values, selects keys in
round-robin order, applies a cooldown after authentication, rate-limit, or
transient provider failures, and exposes only redacted health counters.

Customer care uses the existing conversation, ticket, follow-up, CSAT, and
assignment APIs. The UI adds contextual quick actions rather than creating a
second workspace. Sales orders gain nullable logistics metadata and an audited
update route, preserving tenant filtering and current lifecycle transitions.

## Acceptance criteria

- A configured pool of five keys is selected fairly and a failed key is skipped
  during its cooldown.
- LLM and embedding calls can retry once with another available key without
  logging the key.
- Customer 360 exposes ticket, note, assignment, takeover, and follow-up
  actions without leaving the selected customer context.
- An order can store a provider, tracking code, and shipment status, and these
  fields are visible in the order workspace while remaining tenant-scoped.
- The release checklist covers migrations, Docker health, provider smoke tests,
  AI commerce scenarios, backup, rollback, and secret rotation.
- Existing backend and frontend tests remain green; new behavior has focused
  tests for key rotation, logistics isolation, quick-action wiring, and release
  configuration.
