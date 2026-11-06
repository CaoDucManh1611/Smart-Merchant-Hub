# Smart Merchant Hub Sales Journey privacy hardening design

_Design review and implementation status - 2026-11-05 15:02 +07:00._

## Implementation status

```text
PRIVACY HARDENING IMPLEMENTED: NO
PRIVACY HARDENING DESIGN: COMPLETE FOR HANDOVER
SOURCE EDITS: BLOCKED BY WORKTREE COLLISION RISK
```

## Current durable envelope

`SerializedJourneyState` currently wraps the full `SalesJourneyState`. The state includes scope identifiers, stage/confidence, intent, product interest, purchase signals, collected slots, missing slots, constraints, objection, recommendations, actions, handoff reason, version and timestamp. Three fields are typed as `dict[str, Any]`, and several strings/lists are unbounded.

The bridge writes this envelope as `sales_journey_state` in `CollectionFlowResult.metadata`. The existing turn service places it in `CrmJob.payload.collection_metadata`; the outbound writer accepts the metadata and persists it in `Message.metadata_`.

## Minimum persisted schema proposal

| Persisted field | Proposed contract |
|---|---|
| Scope | Tenant, conversation and optional customer identifiers required for exact isolation; no raw contact data |
| Version/time | Integer schema version, `updated_at`, and an explicit expiry policy |
| Journey | `JourneyStage` enum and `NextBestAction` enum only |
| Goal | Opaque deterministic goal ID only; no customer wording |
| Catalog | Verified product/service IDs only; bounded list |
| Planning flags | Small allowlist of booleans/enums such as comparison requested, purchase intent observed, follow-up authorized, and human handoff required |
| Handoff | Bounded enum/reason code, not free-text transcript or customer explanation |
| Excluded | Raw messages, phone/email/address, credentials/tokens, health data, arbitrary nested dictionaries, free-text constraints and recommendations |

The exact TTL, retention days and consent purpose remain policy decisions. Do not silently truncate a value that could change a sales decision; reject the durable state and use a safe legacy/fresh-turn fallback instead.

## Required hardening patch plan

1. `sales_journey_contracts.py`: introduce a dedicated persisted-state model with `extra="forbid"`, enum-only fields, bounded strings/lists and no `Any` fields.
2. `sales_journey_adapter.py`: validate and sanitize at the serialization boundary; reject forbidden keys recursively, unsupported fields, excessive depth, excessive list counts and total JSON bytes. Return an explicit failure that the caller can convert to legacy fallback.
3. `sales_journey_graph_bridge.py`: persist only the sanitized envelope; do not include `JourneyDecision.needs`, response guidance, objection text or raw input in the durable metadata.
4. `conversation_turn_service.py` and `auto_reply_service.py`: enforce the journey metadata allowlist before `CrmJob.payload` or `Message.metadata_` writes; do not rely on caller comments or blacklist-only filtering.
5. `privacy_service.py`: define how consent revocation and lifecycle deletion reach `Message.metadata_` and `CrmJob.payload`; keep audit records redacted.
6. Add privacy regression tests only after an isolated snapshot is supplied.

## Current positive controls

- Top-level Pydantic models reject unknown fields.
- Exact tenant/conversation/customer scope is checked on load.
- Schema version and 30-minute freshness are checked on load.
- The journey modules do not log or print message content.
- Engine decisions report zero LLM/network calls and no side effects.

These controls do not make the current envelope privacy-safe because nested arbitrary values remain accepted and TTL is not physical deletion.

**PRIVACY HARDENING DESIGN: READY FOR ISOLATED IMPLEMENTATION; NOT IMPLEMENTED IN THIS SHARED WORKTREE.**
