# Phase 2.2 Graph integration report

## Entry point

The existing runtime path remains:

`conversation_turn_service.dispatch_chatbot_turn`
→ `conversation_graph.graph_reply`
→ existing LangGraph `plan` / `authorize` / `tools` / `workflow` / `compose` nodes.

The bridge is called inside `graph_reply`, after the trusted workspace
configuration and final Phase 1 context are available, and before deterministic
shortcut returns and the compiled Graph planner. The legacy shortcuts remain
authoritative for their existing safe cases; their results now carry the
server-generated journey metadata when the flag is ON.

## Configuration and inputs

With `SALES_JOURNEY_ENGINE_ENABLED=False` (the default), the bridge is not
called and the existing Graph planning path is preserved.

With the flag ON:

1. `get_workspace_config(db, business_id)` supplies trusted capability and
   persisted industry configuration.
2. `IndustryResolver`, `discover_needs`, `sales_brain_context` and
   `playbook_guidance` provide the final Phase 1 resolution.
3. The bridge receives `BrainResolution`, scoped reply memory, tenant,
   conversation and customer identity, and the trusted capability snapshot.
4. The engine makes one deterministic decision. The already-computed
   `BrainResolution` prevents a duplicate Needs Discovery call.
5. The decision is mapped into the existing Graph plan. The bridge never
   authorizes a tool and never executes a workflow.

## Action mapping

| Journey action | Existing Graph plan |
|---|---|
| Discover/qualify/ask clarification | `chat`, one clarification |
| Search catalog / retrieve knowledge / recommend / compare / objection / after-sales | `answer` with requested tools |
| Offer booking / quote / order | `workflow` with requested workflow |
| Offer human handoff | `handoff` |
| Answer directly / authorized follow-up | `answer` when tools are requested, otherwise `chat` |

The existing `_resolve_plan` and `authorize_plan` still re-check capability,
dependency, workflow and conversation-state authorization. The bridge's
`ToolPlan` is a request, not permission.

## Safety preservation

- Catalog, calendar, privacy, safety and ticket shortcuts remain deterministic.
- Answer Guard, citation validation, claim verification and money calculation
  remain in the existing `compose` path.
- Closing actions remain offers; the engine does not create a transaction.
- Missing evidence, disabled capability and missing dependency remain
  fail-closed through the existing resolver/compose behavior.
- A bridge, persistence or state error logs a warning and continues through
  the legacy planner without a provider retry or extra LLM call.

## Persistence handoff

`sales_journey_metadata` is placed in the Graph state and merged into final,
shortcut, capability and handoff `CollectionFlowResult.metadata`. The existing
turn service writes that metadata to the CrmJob payload and passes it to the
existing outbound Message metadata writer. No migration or new checkpoint
store was added.

## Rollback

Set the trusted server flag to `False`; no code rollback is required to restore
the legacy planner path. If the code change itself must be reverted after
Agent 1's work settles, remove the bridge import/call, the five journey fields
in `TurnState`, the plan/workflow/metadata handoff, and the optional engine
argument. Do not reset the shared dirty worktree.

## Required post-merge regression

Run the Phase 2/2.1/2.2 tests, Capability Registry, Universal Sales Brain,
Conversation Graph, chatbot routing/follow-up, business workflow, catalog and
recommendation, Answer Guard/RAG, tenant isolation, and API tests in the
supported backend environment. Then run a flag-OFF Graph smoke test, a flag-ON
mocked Graph test, multi-turn state persistence, stale/corrupt state,
capability-disabled/dependency-missing, handoff failure, and transaction
confirmation cases. Provider/live DB/runtime checks are outside this offline
handover.
