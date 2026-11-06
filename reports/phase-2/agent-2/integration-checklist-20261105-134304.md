# Phase 2.1 Graph integration checklist

Status: design handover only. The engine is **not integrated** and the feature
flag is not present or enabled in this pass.

## 1. Entry point and insertion order

Later integration should use the existing `graph_reply(...)` entry point in
`backend/app/services/conversation_graph.py` (currently around line 147).
The safest first insertion point is after the final tenant-scoped memory and
Sales Brain context are available (currently around lines 1217–1227), before
the `StateGraph` is compiled/invoked (currently around line 1286). This gives
the engine the final `memory`, `resolved_sales_context`,
`industry_guidance` and trusted `workspace_config` for the same turn.

Required order:

1. Read a trusted server-side feature flag; default must be `False`.
2. Load only the approved, versioned journey state for this tenant,
   conversation and customer. Reject stale/corrupt/cross-scope state.
3. Resolve final Phase 1 industry context and Needs Discovery using the
   existing `discover_needs`/`sales_brain_context` path or the
   `UniversalSalesBrainAdapter`; do not create another extractor/agent.
4. Construct/evaluate one `SalesJourneyEngine` decision for the current turn.
5. Translate the decision into the existing Graph `TurnState` plan/context.
6. Retain current `authorize_plan` as the final capability gate.
7. Execute existing SQL/RAG/recommendation/workflow nodes only after that gate.
8. Persist the new versioned state only through an approved existing durability
   boundary after the turn result is known; never use the test in-memory
   adapter in production.

## 2. Proposed payload mapping

```python
decision = engine.evaluate(
    tenant_id=business_id,
    conversation_id=conversation.id,
    customer_id=getattr(conversation, "customer_id", None),
    message=query,
    state=loaded_serialized_journey_state,
    memory=memory,
    industry_configuration=persisted_industry_config,
    capability_config=workspace_config,
    transaction_evidence=verified_transaction_evidence,
    workflow_evidence=verified_workflow_evidence,
    follow_up_authorized=explicit_follow_up_authorization,
)
```

`persisted_industry_config` must come from the trusted tenant workspace
configuration. `memory` must remain the existing short-lived, scoped memory
shape. `transaction_evidence` and `workflow_evidence` must be populated only
from an existing verified workflow result, never from customer wording alone.

## 3. State persistence decision required before coding

The Phase 2 package intentionally has no application persistence. The current
Graph documentation says durability belongs to existing `CrmJob` payloads and
conversation/order tables; the existing `conversation_memory.py` is a
short-lived reply-memory service with a 30-minute TTL, not yet a declared
Sales Journey state store. The integration owner must choose and document one
approved existing boundary (prefer an existing job/conversation payload over a
new table or migration), then use `serialize_state()`/
`deserialize_state()` with tenant/conversation/customer checks. Do not silently
persist the journey in a new database column or table in this handover.

## 4. Next Best Action mapping

| Engine action | Existing Graph behavior to request | Guard |
|---|---|---|
| `ANSWER_DIRECTLY` | Existing answer/chat route as appropriate | Facts still require existing evidence/Answer Guard. |
| `ASK_CLARIFICATION`, `DISCOVER_NEED`, `QUALIFY_NEED` | Put final Needs Discovery context into `TurnState`; current `model_plan` can return `chat` with one `next_best_question`. | Do not add a second LLM call or ask multiple essential questions. |
| `SEARCH_CATALOG` | `answer` with `catalog` tool | `resolve_capability_request`, current catalog rows and current price evidence. |
| `RETRIEVE_KNOWLEDGE` | `answer` with `knowledge` tool | Authoritative RAG evidence and citation validation. |
| `RECOMMEND_OPTIONS` | `answer` with `recommendations` (existing node may pair current `catalog`) | Recommendation evidence plus current catalog facts; preserve consented memory boundaries. |
| `COMPARE_OPTIONS` | `answer` with `catalog` | Current comparison basis and source-backed attributes only. |
| `ADDRESS_OBJECTION` | `answer` with catalog or knowledge according to `ToolPlan` | Use declared evidence requirements; no invented discount, fitment, warranty or delivery claim. |
| `OFFER_BOOKING`, `OFFER_QUOTE`, `OFFER_ORDER` | Existing `workflow` path only after explicit confirmation/collection authorization | Offer is not a transaction; preserve current workflow authorization and no-side-effect rule. |
| `FOLLOW_UP_IF_AUTHORIZED` | Existing answer/chat path unless explicit authorized follow-up workflow exists | Never send or mutate from a planning decision alone. |
| `AFTER_SALES_SUPPORT` | Existing answer with verified order/transaction and policy evidence | Without proof, engine already routes to handoff. |
| `OFFER_HUMAN_HANDOFF` | Existing handoff route only if its ticket/assignment contract succeeds | Do not claim assignment if the handoff result is not accepted and verified. |
| `PAUSED` | Non-pressuring chat/answer with no sales action | Respect stop/decline; no forced closing. |

The Graph must treat `ToolPlan` as a recommendation to the existing planner,
not as an authorization. The existing `authorize_plan` node around line 271
must re-check the current tenant capability snapshot before `tools` or
`workflow` execution.

## 5. SQL, RAG and Recommendation boundaries

- SQL/catalog: use existing `current_offerings()`/
  `get_current_offering()` and the existing catalog node. The engine must not
  issue SQL or inspect product rows.
- RAG/knowledge: use the current `retrieve`/evidence path. The journey state
  and playbook guidance are interpretation/planning context, not citations.
- Recommendation: use the existing `recommendation_evidence()` path and pair
  ranked candidates with current catalog evidence as the Graph already does.
- Workflows: keep the existing `advance_business_request()`/workflow node and
  confirmation semantics. Journey closing never creates order, booking, quote
  or payment state.

## 6. Answer Guard preservation

Do not bypass or weaken the current `compose` validations: source IDs,
authoritative catalog IDs, `has_valid_citations`, `customer_facing_answer`,
`verified_money_calculation`, claim verification and retry/fallback behavior
remain the response authority. A journey recommendation, objection category or
industry playbook rule must never be copied into factual evidence.

## 7. Feature flag and rollback

- Add a trusted server-side setting such as
  `SALES_JOURNEY_ENGINE_ENABLED`, default `False`, in the later integration
  change. Do not read it from customer text or client-provided request data.
- Flag OFF must preserve the current Graph path and existing plan/authorization
  behavior byte-for-byte as far as practical.
- Rollback is a flag-off operation; no migration or state rewrite should be
  needed. If a malformed state or engine exception occurs, log a scoped
  reason and continue through the legacy plan path without provider retries.
- If metrics/regression checks show increased handoffs, extra LLM calls,
  citation failures, or workflow starts, turn the flag OFF and retain the
  serialized state for offline diagnosis only.

## 8. Regression required after integration

Run in the supported backend environment:

```text
pytest tests/test_sales_journey_engine.py tests/test_sales_journey_policy.py tests/test_sales_journey_integration_contract.py -q
pytest tests/test_conversation_graph.py tests/test_chatbot_answer_routing.py tests/test_business_workflow_regressions.py tests/test_workspace_modules.py tests/test_capability_registry.py tests/test_universal_sales_brain.py -q
```

Also add integration tests for flag OFF/ON, state load/save scope and TTL,
Graph plan translation, capability-disabled and dependency-missing behavior,
catalog/RAG/recommendation evidence, Answer Guard failure, human handoff
failure, no extra LLM calls, no transaction before confirmation, topic switch,
pause/decline and after-sales proof. Runtime/provider/production checks remain
outside this Phase 2.1 task.

