# Phase 2.2 persistence decision

## Decision

Use the existing server-generated outbound `Message.metadata_` as the
durable owner for the versioned Sales Journey envelope, with the existing
`CrmJob.payload` as the turn-level audit/delivery handoff. Do not add a table,
migration or production `InMemoryJourneyStateAdapter`.

## Write path

`graph_reply` returns `CollectionFlowResult.metadata` containing the serialized
`sales_journey_state` envelope plus action/stage/reason metadata. The existing
`conversation_turn_service.dispatch_chatbot_turn` already:

1. stores `collection_reply` and `collection_metadata` in the `CrmJob` payload;
2. passes the metadata to `send_text_reply`;
3. persists it through `_save_auto_reply_outbound` and `_reply_metadata` on the
   sent outbound `Message`.

The journey bridge therefore reuses an existing tenant/conversation persistence
owner and needs no schema change.

## Read path and fail-closed rules

`load_latest_journey_state` joins `Message` to `Conversation` and filters the
exact `business_id`, `conversation_id`, `customer_id`, outbound direction and
sent status. `deserialize_state` then enforces schema name/version, exact
scope, customer binding and the 30-minute TTL. Empty, corrupt, cross-scope or
stale state is ignored. A database/query failure returns `unavailable`; Graph
continues on the legacy path rather than retrying or inventing state.

## Delivery and handoff boundaries

- If a provider delivery is unknown, the turn job retains the metadata but the
  next read only trusts a `sent` outbound Message. This intentionally resets
  the journey on unconfirmed delivery rather than risking stale progression.
- Handoff success/failure and capability-denied replies carry the same state
  metadata through the turn job and outbound message path.
- Journey state records planning context only. It is not transaction proof and
  cannot create an order, booking, quote or payment.
- Evidence, transaction confirmation, Answer Guard and workflow records remain
  owned by the existing Graph/RAG/workflow services.

## Test evidence

The offline bridge tests cover round trip, exact tenant/conversation/customer
scope, stale state, persistence failure fallback, feature flag default and
state metadata status. The live SQLAlchemy/Graph path could not be imported in
this environment because `langgraph` is absent; no production database was
used.

## Integration owner checklist

- Keep the metadata key `sales_journey_state` stable.
- Keep `Message.metadata_` and CrmJob JSON serialization server-generated only.
- Preserve the `sent` filter and exact scope checks.
- Do not replace this with global cache or production in-memory state.
- Add a supported-environment test that writes a turn and reads the next-turn
  state through the real message/job path.
