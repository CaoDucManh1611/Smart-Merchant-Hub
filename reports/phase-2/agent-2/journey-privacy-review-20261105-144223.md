# Smart Merchant Hub Sales Journey state privacy review

_Read-only review of serialization and persistence boundaries — 2026-11-05._

## Serialized fields

`SerializedJourneyState.state` currently serializes every field of `SalesJourneyState`:

- Tenant, conversation and customer identifiers
- `active_goal_id`, stage and confidence
- Customer intent and purchase-readiness signals
- Product/service interest
- Collected slots and missing slots
- Customer constraints
- Objection type and selected recommendations
- Last action, next action and handoff reason
- State version and `updated_at`

`JourneyDecision.needs`, `objection` and `response_guidance` are not included in the journey envelope by `_metadata_for_decision`; only the state plus stage/action/reason metadata is forwarded.

## Findings

| Review item | Result | Evidence |
|---|---|---|
| Raw message in normal engine state | PASS by default | `StageEvidence.message` is not part of `SalesJourneyState`; the engine does not assign the raw input to a state field. |
| Payment secrets | PASS by scope | No payment/provider fields are created by the Phase 2 serializer or engine. |
| Tenant/conversation/customer scope | PASS | Loader filters all three known identities plus outbound `sent`; deserialization rechecks scope. |
| Schema version and TTL | PARTIAL | Version `1` and 30-minute freshness are enforced on read. TTL is not a database deletion or retention mechanism. |
| Arbitrary free text/PII | FINDING | `purchase_readiness_signals`, `collected_slots` and `customer_constraints` are `dict[str, Any]`; `customer_intent`, `product_or_service_interest` and `handoff_reason` are unbounded strings. |
| Whitelist/redaction | FINDING | No serialization allowlist, redaction step, maximum field length, maximum list size or envelope byte limit exists. |
| Consent revocation | FINDING | The state has no consent version/decision and no purge hook. Existing reply memory is scoped and TTL-checked, but TTL does not remove metadata from `Message` or `CrmJob`. |
| Journey-module logging | PASS | No logger/print calls were found in the five Sales Journey modules. The Graph fallback logs only the exception type. |

## Synthetic proof of the privacy finding

An offline serializer probe used only synthetic placeholders. The serializer preserved arbitrary values supplied through the contract:

```text
serialized_state_fields: all 20 SalesJourneyState fields
arbitrary_slot_preserved: {'phone': 'SYNTHETIC_PHONE', 'raw_message': 'SYNTHETIC_RAW_MESSAGE'}
raw_message_present: True
sensitive_placeholder_present: True
serialized_bytes: 747
```

This does not prove that the current deterministic extractor automatically stores raw messages. It proves that the persistence contract accepts and stores them if supplied through state/memory integration. The same applies to sensitive values placed in constraints or slots.

## Persistence path

The server-generated metadata path is:

`CollectionFlowResult.metadata` → `CrmJob.payload.collection_metadata` → `send_text_reply(extra_metadata=...)` → `Message.metadata_`.

The metadata writer merges caller metadata without field-level journey filtering. Therefore the privacy boundary must be enforced before `CollectionFlowResult.metadata` reaches the turn writer, or at the serializer/metadata writer boundary.

## Required hardening after isolation is resolved

Do not apply these changes in the current collision-risk worktree. The integration owner should decide and test:

1. Replace broad persisted `Any` fields with an allowlisted, bounded planning schema.
2. Reject raw message, phone, email, address, health, payment and credential-like keys at serialization.
3. Bound string lengths, list counts, nested depth and total JSON bytes.
4. Add consent/revocation behavior and an actual retention/deletion owner; do not call TTL-based read invalidation deletion.
5. Add redaction/metadata tests and a migration-free cleanup policy for existing `Message.metadata_` rows if required.

**PRIVACY REVIEW: FINDINGS.** No hardening was performed because the Agent 2/Agent 1 workspace boundary is not verified.
