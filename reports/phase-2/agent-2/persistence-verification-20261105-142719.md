# Smart Merchant Hub Phase 2.4 persistence verification

## Selected persistence owner

The existing server-generated metadata path remains the owner:

`Graph Reply` → `CollectionFlowResult.metadata` → `CrmJob.payload.collection_metadata` → `send_text_reply(extra_metadata=...)` → outbound `Message.metadata_` → next-turn `load_latest_journey_state`.

The Phase 2 bridge does not add a table, migration, checkpoint store, global cache or production `InMemoryJourneyStateAdapter`.

## Isolated DB round trip

A real SQLAlchemy SQLite in-memory schema was created only from the synthetic `customers`, `channels`, `conversations` and `messages` tables. No repository `backend/test.db`, production database or provider was opened.

Observed results:

```text
first_load empty version 1
second_load loaded previous DISCOVERY version 2
tenant_mismatch empty
customer_mismatch empty
delivery_unknown empty
corrupt_version invalid_or_expired
db_round_trip=PASS
```

The permanent regression is `test_sqlite_round_trip_enforces_sent_scope_ttl_and_retry_boundaries` in `backend/tests/test_sales_journey_graph_bridge.py`.

A second synthetic check inserted a duplicate/retry row with the same envelope:

```text
unknown_retry_does_not_hide_sent loaded 4
duplicate_same_state_preserved loaded 4
duplicate_delivery=PASS
```

## Contract checks

- `sales_journey_state` envelope schema version is `1`.
- State TTL is 30 minutes.
- Corrupt, unknown schema, stale and cross-scope state is ignored.
- Only outbound rows with `status == "sent"` are eligible.
- Delivery-unknown rows do not advance the next turn.
- Tenant, conversation and known customer identities are checked together.
- Handoff/capability-denied results remain planning metadata and do not create a transaction.
- Serialized state does not include the raw customer message. The broad `dict[str, Any]` slot fields still require a field-level privacy review before production acceptance; no sensitive production data was used.

## Boundary

`PERSISTENCE DB ROUND TRIP VERIFIED` is YES for the isolated synthetic SQLite contract. It is not a production DB, staging, provider-delivery or live turn-service acceptance claim. The real Graph-to-turn-service runtime path remains blocked by missing `langgraph` and `payos`.
