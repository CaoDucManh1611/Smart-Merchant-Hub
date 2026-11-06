# Phase 2.3 persistence verification

_Offline verification of the multi-turn Sales Journey state path — 2026-11-05._

---

## Verified contract path

The audited path is:

`Graph Reply`
→ `CollectionFlowResult.metadata`
→ `CrmJob.payload.collection_metadata`
→ `send_text_reply(extra_metadata=...)`
→ outbound `Message.metadata_`
→ `load_latest_journey_state` on the next turn.

The existing turn service and outbound metadata writer were not changed in
Phase 2.3. The bridge only supplies the versioned `sales_journey_state`
envelope and server-generated journey metadata.

## Offline evidence

The new bridge tests verify:

- first turn with no prior state starts safely;
- second turn loads a sent state in the same tenant, conversation and customer
  scope;
- state version advances across the two-turn path;
- wrong customer/tenant/conversation state is rejected;
- stale state is rejected;
- corrupt or missing message metadata does not resume state;
- unconfirmed delivery metadata does not resume state;
- persistence query failure falls back to the legacy path and records an
  unavailable status.

The existing Phase 2.1 tests also cover serialization version rejection,
future/stale timestamps, missing customer binding and scoped memory.

## Runtime boundary

This is not a live SQLAlchemy/Graph persistence PASS. The Graph cannot be
imported in the available runtime because `langgraph` is missing, and the task
prohibits production DB access or migrations. The SQL filter and existing turn
writer were source-audited; the real database round trip remains a controlled
merge prerequisite.

## Production safety

- `InMemoryJourneyStateAdapter` remains test-only.
- No new table or migration was added.
- Only sent outbound messages are eligible for resume.
- Delivery-unknown turns fail closed by not becoming the next trusted state.
- Journey state is planning context, not transaction confirmation.
