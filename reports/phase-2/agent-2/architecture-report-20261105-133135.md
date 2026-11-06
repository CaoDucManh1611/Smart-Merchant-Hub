# Phase 2 Universal Sales Journey Engine architecture

## Scope

This implementation adds a deterministic planning layer around the existing
Universal Sales Brain. It does not create a second chatbot, replace LangGraph,
change RAG/catalog/memory/RFM/recommendation code, or activate a production
route.

## Flow

```text
customer message
  -> UniversalSalesBrainAdapter
  -> NeedsDiscovery + playbook guidance
  -> StageEvidence
  -> deterministic transition policy
  -> NextBestAction
  -> existing capability registry authorization
  -> ToolPlan for a later Graph integration
  -> existing evidence verification and natural response
```

The engine returns a `JourneyDecision`. It never executes the tool plan.

## Contracts

`backend/app/services/sales_journey_contracts.py` defines:

- `JourneyStage`: UNKNOWN, DISCOVERY, QUALIFICATION, RECOMMENDATION,
  COMPARISON, OBJECTION_HANDLING, CLOSING, FOLLOW_UP, AFTER_SALES, HANDOFF,
  PAUSED.
- `NextBestAction`: all requested action values, including direct answer,
  discovery, catalog/knowledge retrieval, recommendation/comparison, objection
  handling, quote/booking/order offers, handoff, authorized follow-up and
  after-sales support.
- `SalesJourneyState`: tenant/conversation/customer scope, goal, stage and
  confidence, intent, readiness signals, interest, collected/missing slots,
  constraints, objection, recommendation references, previous/next actions,
  handoff reason, version and timestamp.
- `JourneyDecision`, `StageEvidence`, `ObjectionAssessment`, `ToolPlan` and a
  versioned serialization envelope.

State is current planning state only. It contains no database identity beyond
the supplied scope and does not store raw conversation history.

## Transition rules

- Any stage -> HANDOFF for explicit human request, sensitive context, missing
  authorization/dependency, or an after-sales request without transaction
  evidence.
- Any stage -> PAUSED for a clear customer stop/decline signal.
- UNKNOWN -> DISCOVERY for direct information or incomplete discovery;
  UNKNOWN -> QUALIFICATION when a need is already sufficient.
- DISCOVERY -> QUALIFICATION when essential slots are collected.
- QUALIFICATION -> RECOMMENDATION when the qualified customer asks for a
  recommendation.
- RECOMMENDATION -> COMPARISON on an explicit comparison request.
- RECOMMENDATION -> OBJECTION_HANDLING on a price/quality/compatibility/trust,
  timing, delivery or warranty concern.
- OBJECTION_HANDLING -> RECOMMENDATION when the customer requests an
  alternative after the concern.
- COMPARISON -> CLOSING only on an explicit purchase signal.
- CLOSING -> FOLLOW_UP for a non-confirmed purchase and a follow-up/deferral
  signal.
- CLOSING -> AFTER_SALES only when explicit workflow/transaction evidence is
  supplied; the phrase “let me see” is never treated as a purchase.
- Topic/product/industry changes create a new opaque goal and discard stale
  goal slots while preserving tenant/conversation scope.

The policy intentionally allows direct information and price-first requests to
stay in DISCOVERY and use a catalog/knowledge plan without forcing a full
funnel.

## Next-best-action and capability policy

`sales_journey_policy.py` maps stage, intent, missing slots, objection and
business model to an action. It calls the existing
`resolve_capability_request` only to authorize the proposed plan. It never
auto-enables a capability. A disabled or dependency-blocked catalog,
recommendation, order, booking or quotation path is converted to a human
handoff plan with the missing capability/dependency recorded.

All closing actions are offers only. `transaction_created` remains false and
`side_effects` remains empty.

## Needs discovery and memory seams

`UniversalSalesBrainAdapter` reuses `resolve_industry_profiles`,
`discover_needs`, `sales_brain_context` and `playbook_guidance`. It supports the
existing configured playbooks for fashion, beauty, electronics, automotive,
furniture, F&B, real estate, education, travel, healthcare, B2B,
services/repair, rental and professional services.

`clean_memory_context` accepts only the existing short-lived memory fields.
`deserialize_state` fails closed for missing/corrupt/version-mismatched or
cross-scope state. `InMemoryJourneyStateAdapter` exists only as a disposable
test seam and is not application persistence.

## Safety and cost

- No LLM, network, provider, database, Graph, order, booking, quote or payment
  calls are made.
- `llm_calls` and `network_calls` are explicitly zero in every decision.
- Evidence requirements are carried in `ToolPlan`; the engine does not invent
  price, stock, compatibility, warranty, delivery or policy facts.
- Healthcare/sensitive cues route to HANDOFF without diagnosis or prescription.
- Tenant and conversation scope are checked before prior state or memory is
  reused.
