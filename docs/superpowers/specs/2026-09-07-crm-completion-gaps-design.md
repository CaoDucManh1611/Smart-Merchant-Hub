# CRM Completion Gaps Design

**Date:** 2026-09-07
**Branch:** `crm-completion`

## Goal

Complete the remaining CRM capabilities without breaking the existing Customer 360, omnichannel inbox, sales/purchase, RAG, and experimentation contracts. The work must move incomplete primitives toward production-safe CRM workflows, not merely add screens or store unvalidated JSON.

## Scope

The scope covers the gaps found in the current repository:

1. CI/CD quality gates and deployment safety.
2. Revenue attribution and lead-to-order conversion.
3. Lead activities, pipeline reporting, and report dimensions.
4. SLA/workflow scheduling and durable retries.
5. Granular team permissions.
6. Durable RAG ingestion/run operations.
7. Rule recommendation evidence and approval flow.
8. Supervised feature/model lifecycle.
9. A/B experiment metrics and guardrails.
10. Contextual-bandit policy selection and reward updates.

Existing Customer 360, Unified Timeline, Product/Order, Ticket, and Customer Facts behavior remains backward compatible. New records are tenant-scoped by `business_id` and all cross-resource references are validated inside the active tenant.

## Recommended architecture

### 1. Shared CRM attribution layer

Add tenant-owned touchpoints and attribution records rather than inferring revenue from a single channel column:

- `revenue_touchpoints`: customer/order/lead/conversation source events with channel, source, campaign, occurred time, and metadata.
- `revenue_attributions`: order amount allocated to one or more touchpoints using an explicit model (`first_touch`, `last_touch`, `linear`, `time_decay`, `manual`), with decimal weight and attributed amount.
- `lead_conversions`: immutable link from a lead to a converted sales order and conversion actor/time.

The initial automatic source is existing conversation/channel history; UTM/campaign fields remain optional. Reports expose both raw revenue and attributed revenue so the current channel report remains compatible.

### 2. Durable operations jobs

Use a database-backed `crm_jobs` table for scheduled work. Jobs have tenant, kind, payload, status, attempts, `run_at`, `locked_at`, `last_error`, and an idempotency key. A small worker/dispatch command claims due jobs, runs bounded retries with exponential backoff, and records audit/notification outcomes. The HTTP dispatch endpoint remains as a safe manual trigger for development and smoke tests.

Workflows and SLA checks use the same job contract. Existing `workflow_runs` remain the business-level execution history; jobs are the delivery mechanism. No provider credential or message body is written to job errors.

### 3. Permission policy

Keep owner/admin/agent/viewer roles as defaults, then add tenant-owned permission overrides (`resource`, `action`, `effect`) with an effective-policy endpoint. The role matrix remains the fallback; deny rules win over role grants. Existing `require_write_access` and `require_admin_access` are adapted to the shared policy evaluator, preserving development header compatibility and production bearer enforcement.

### 4. RAG operations

Persist RAG runs/jobs in PostgreSQL while retaining the JSONL logger as a local diagnostic sink. Document ingestion and reindex requests enqueue jobs instead of spawning unbounded request threads. Each run records phase, provider, retry state, source document IDs, chunk count, and sanitized error metadata. Retrieval keeps the current hybrid vector/lexical fallback and source citations.

### 5. Measurable AI lifecycle

- Rule suggestions store evidence references, proposed workflow version, reviewer, and approval outcome. Accepted suggestions are explicitly converted to a workflow version; approval alone never silently mutates an active workflow.
- Supervised ML adds model versions and train/evaluation runs over immutable feature snapshots. The first implementation uses a deterministic, dependency-light baseline with holdout metrics and a versioned JSON artifact; inference always names the model version.
- A/B experiments add exposure events, metric aggregates, minimum sample/stop criteria, and a report endpoint. Existing assignment/outcome endpoints remain compatible.
- Bandits add a policy configuration and deterministic epsilon-greedy selection over experiment arms. Decisions/rewards update persisted arm statistics; every selection records policy version and context hash for replay.

## API/UI contracts

- Existing endpoints keep their response fields and status semantics.
- New write endpoints return `401`/`403`/`404`/`409`/`422` consistently with current auth and tenant behavior.
- Reports accept date, channel, owner, source, attribution model, and status filters.
- UI additions stay within the current Smart Merchant Hub visual system and expose loading/error/empty states. No legacy food branding is reintroduced.

## CI/CD acceptance criteria

CI must run backend tests, frontend tests, Alembic upgrade/head verification, frontend production build, backend/frontend Docker builds, and a compose health smoke test. CD must publish immutable images, run migrations before rollout, verify `/health` and frontend readiness, and expose a failed rollout as non-success without silently promoting `latest`.

## Verification strategy

Each slice follows red-green tests before implementation. The final gate runs:

- Full backend pytest suite.
- Full frontend Node test suite.
- `python -m compileall -q app alembic tests`.
- Alembic upgrade/current on a disposable PostgreSQL database.
- Frontend production build and Docker image builds.
- API smoke checks for tenant isolation, attribution, job dispatch, permissions, RAG reindex, experiment metrics, and bandit decisions.
