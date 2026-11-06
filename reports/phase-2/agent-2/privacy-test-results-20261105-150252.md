# Smart Merchant Hub Sales Journey privacy and contract test results

_Synthetic offline evidence only; no customer data used - 2026-11-05 15:02 +07:00._

## Current result

```text
PRIVACY REGRESSION TEST SUITE: NOT ADDED (source edits blocked)
PRIVACY TEST VERIFICATION: BLOCKED/PARTIAL
CURRENT PYTEST HARNESS: TIMEOUT BEFORE RESULT
```

## Synthetic serializer probe

The probe used only synthetic placeholders and exited 0:

```text
SERIALIZED_FIELDS=active_goal_id,collected_slots,conversation_id,customer_constraints,customer_id,customer_intent,handoff_reason,last_action,missing_slots,next_best_action,objection_type,product_or_service_interest,purchase_readiness_signals,selected_recommendations,stage,stage_confidence,state_version,tenant_id,updated_at
ARBITRARY_SLOT_PRESERVED=True
NESTED_SENSITIVE_PRESERVED=True
CROSS_TENANT_ACCEPTED=False
VALID_SCOPE_ACCEPTED=True
VERSION_MISMATCH_REJECTED=True
STALE_REJECTED=True
```

This proves the current privacy finding: the serializer preserves arbitrary values supplied through `collected_slots` and nested constraints. It does not prove that the normal extractor automatically stores raw messages.

## Required regression matrix

| Case | Current evidence | Required post-hardening result |
|---|---|---|
| Arbitrary PII key | FINDING; arbitrary slot preserved | Reject and fallback without logging value |
| Raw message | FINDING when supplied through a nested slot | Reject at serializer boundary |
| Nested sensitive value | FINDING; nested email placeholder preserved | Reject at any depth |
| Oversized string | Not bounded by current contract | Reject, never silently truncate |
| Oversized envelope | No byte cap present | Reject and use safe fallback |
| Unsupported top-level field | Pydantic `extra="forbid"` is a positive control | Keep rejection covered by test |
| Safe enum and opaque ID | Current model accepts valid values | Accept only bounded/verified values |
| Cross-tenant state | Rejected | Keep exact tenant/conversation/customer test |
| Corrupt/version-mismatched state | Rejected | Keep fail-closed fallback test |
| Consent/purpose mismatch | No journey-purpose enforcement | Must reject state for an unauthorized purpose |
| Error log leakage | No logger/print in journey modules by static scan | Add assertion that exception logs contain no payload |
| Provider/LLM calls | Direct engine probe completed without them | Keep no-call assertion |
| Transaction side effects | Existing engine contract reports none | Keep no-transaction assertion |

## Pytest classification

The existing Agent 1 offline full backend evidence is green at `2,149 passed, 3 skipped, 39 warnings, 37 subtests`, but it is not a privacy-hardening suite and does not verify Graph runtime. Fresh pytest attempts in this checkpoint timed out before collection or test output, including a Phase 2-only run and a single-test run. Therefore no fresh pytest PASS is claimed for this checkpoint.

**PRIVACY TEST RESULT: CURRENT CONTRACT HAS FINDINGS; HARDENING TESTS PENDING ISOLATED WORKSPACE.**
