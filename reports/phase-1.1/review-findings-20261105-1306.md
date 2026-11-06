# Phase 1.1 — Review findings and status

**Recorded:** 2026-11-05 13:06 +07:00  
**Branch:** `codex/rag-rfm-all-updates-20261104`  
**Fresh independent review:** **REVIEW PENDING**

## Fresh Gauss review request

A read-only final-diff review was sent to the existing Gauss agent, specifically asking it to check capability bypasses, tenant isolation, appointment status/reminder side effects, payment readiness/decryption, RFM/consent, and default LLM-call behavior. One 30-second wait after the request timed out without a final result. No independent PASS is claimed.

## Historical Gauss findings checked against current code/tests

| Historical finding | Current disposition | Evidence / limit |
|---|---|---|
| P1: direct `/api/chat` and `/api/chat/stream` could read catalog data while retail capability was off | **Addressed in working tree; regression tested** | Authorization now precedes `answer_from_crm`, retrieval, and live product context. `test_recommendations_api.py` asserts the denied path does not query those sources. No live request replay. |
| P2: LangGraph could probe product identity before authorization | **Addressed in working tree; regression tested** | Product identity lookup is guarded by current-turn capability authorization; graph test covers service-only plan. |
| P2: auto-reply SKU label formatting could query Product without catalog permission | **Addressed in working tree; regression tested** | The formatter gets a permission flag and skips product lookup by default; routing test covers unauthorized path. |
| Appointment update could mutate schedule/status or enqueue a reminder when appointment capability was off | **Addressed in working tree; regression tested** | Only notes-only update is accepted; denied mutations stop before appointment queries; notes-only edit does not enqueue reminders. GET history is retained. |
| Payment capability could be treated ready from presence of settings alone | **Addressed in working tree; regression tested with mocks** | Supported bank, decryptable account, and account shape are checked per tenant; corrupt ciphertext and another tenant remain not ready. No secret is printed. |

The older review log also described risks around FAQ reuse-purpose consent, price association through product aliases, calendar-history context, and reindex recovery after crashes. Some related code/tests exist in the current tree, but the new final independent reviewer did not return to confirm their final status. FAQ reuse must not be presented as customer-consented unless the applicable purpose is explicit. No production claim is made for these areas.

## Quality and acceptance boundary

- Offline tests establish exercised behavior for listed fixtures; they do not prove no bypass exists in every endpoint or prove live tenant behavior.
- Full backend suite has a prior 88-failure result and was not rerun after the final capability-order change; failure causes remain unclassified in this handover.
- No server, staging, PostgreSQL runtime, provider, or production tenant was used.
- **Review status remains pending.** Do not call Phase 1.1 independently reviewed or production accepted until Gauss returns and outstanding full-suite/runtime acceptance is resolved.
