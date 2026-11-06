# Phase 2 Agent 2 integration plan

## Current boundary

The implementation is READY_FOR_INTEGRATION but deliberately not integrated.
The following existing files were not modified and remain Agent 1/integration
ownership boundaries:

- `backend/app/services/conversation_graph.py`
- `backend/app/services/universal_sales_brain.py`
- `backend/app/services/capability_registry.py`
- `backend/app/tenancy/workspace_modules.py`
- `backend/app/api/chat.py`
- `backend/app/api/workspace.py`
- `frontend/src/App.vue`
- existing Phase 1/1.1 tests

## Proposed later wiring

1. After Phase 1/1.1 is stable, construct one `SalesJourneyEngine` in the
   existing chat planning path. Do not create a second chatbot or default-on
   route.
2. Pass the trusted tenant/business configuration, conversation id and
   customer id. Resolve needs through `UniversalSalesBrainAdapter` and pass
   only the existing short-lived memory shape.
3. Load/save the versioned `SalesJourneyState` through the existing
   Conversation Memory integration. Do not create a new migration or table.
4. Feed `JourneyDecision.next_best_action`, `ToolPlan`, needs context and
   playbook guidance into the existing Graph planner. The Graph remains the
   executor and natural-response owner.
5. Before any catalog, knowledge, recommendation, booking, quote or order
   node executes, retain the `ToolPlan` capability decision and re-check
   current authorization/evidence in the existing workflow.
6. Keep closing actions as offers until the existing authorized workflow has
   confirmed a transaction. Only then pass transaction evidence for an
   AFTER_SALES decision.
7. Add an explicit feature flag/observability path owned by the integration
   change; this Phase 2 package does not enable one.

## Expected adapter payload

```python
decision = engine.evaluate(
    tenant_id=tenant_id,
    conversation_id=conversation_id,
    customer_id=customer_id,
    message=customer_text,
    state=serialized_state_from_existing_memory,
    memory=existing_reply_memory,
    industry_configuration=trusted_industry_config,
    capability_config=trusted_capability_config,
)
```

The executor should consume `decision.tool_plan` and must not infer that a
plan is permission to perform a side effect. The current implementation never
calls the executor.

## Integration acceptance checks

- Existing Graph and Phase 1/1.1 tests remain green.
- No default extra LLM call is introduced.
- Disabled capability and missing dependency remain fail-closed.
- State cannot cross tenant, conversation or customer scope.
- Existing memory remains append-only/TTL-governed by its own service.
- Price, stock, fitment, warranty, delivery and policy claims remain tied to
  current authoritative evidence.
- Closing offer does not create an order/booking/quote.
- AFTER_SALES requires transaction evidence.
- Production/runtime verification is performed only after the wiring change,
  separately from this offline Phase 2 result.

## Integration blockers

- The pytest package is unavailable in the current runtime, so the full
  repository test command could not be executed here.
- Agent 1's uncommitted Phase 1/1.1 work must settle before touching the Graph
  or API integration boundaries.
