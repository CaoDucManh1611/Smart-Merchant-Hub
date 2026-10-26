# RAG stability rollout

Status: in progress; not certified for production.

## Acceptance gates
- Current CRM price, availability and product state override historical replies.
- Deleted/archived products cannot be recommended.
- Knowledge replacement must be explicit; ambiguous conflicting policies require clarification.
- Same-conversation tests: add, update price/stock, delete/reimport same SKU.
- Retail, appointments and rentals must pass independent fixtures.
- Backend and worker must run the same revision.
- Tenant isolation and provider failure tests must pass.

## Implemented in this rollout
- Inject current product evidence before no-context fallback, including when document retrieval is empty.
- Explicit prompt rule: previous assistant statements are not current facts.

## Outstanding before business deployment
- Consolidate overlapping routers and remove industry-specific hardcoded conclusions.
- Knowledge revision/replacement lifecycle.
- Version reporting for backend and worker.
- Meta outbound echo reconciliation and end-to-end duplicate tests.
- Full multi-industry acceptance suite and staging load/failure testing.

## Additional verified changes
- Shared router prioritizes broad catalog discovery consistently with serving.
- Unknown short business questions now reach retrieval instead of being dropped as smalltalk.
- Document availability API and UI allow explicit disable/enable; disabled sources are excluded by ready-only retrieval.
- Disabled documents cannot be reindexed implicitly.
- Latest verification: 121 focused backend tests passed; frontend production build passed.
- Document availability state transitions checked with an isolated test double.

## Still open
- Automatic revision linking and atomic replacement of documents.
- Full removal of industry-specific routes.
- Worker/backend loaded revision comparison.
- Meta duplicate reconciliation.
- Staging acceptance, load and failure tests across retail, appointments and rentals.

## Rollout 2026-10-23: five workstreams
1. Explicit replacement endpoint + UI: locks both tenant-owned documents, requires ready replacement, disables old source atomically; audit retains replacement ID. Replaced documents cannot be implicitly reactivated by reindex.
2. Multi-industry baseline: metadata offering_type=service/rental supported; service billing_unit and appointment-specific availability wording. Legacy industry heuristics remain and require further evaluation before removal.
3. Runtime revision: /health reports loaded/source fingerprint; worker records loaded fingerprint. scripts/check-runtime-revisions.ps1 rejects mismatches. Verified matching after restart.
4. Meta reconciliation: delivery_unknown outbound messages now eligible for confirmation from history, imported row excluded from candidates. Does not resend. Isolated regression passed; no fresh external Meta test yet.
5. Acceptance regression: 128 focused tests passed, including three offering types, updated catalog price, replacement readiness and shop boundary, uncertain outbound echo reconciliation. Frontend production build passed. These are component/contract checks, not a completed staging business acceptance.

Remaining release gates: full removal of legacy industry heuristics, UI configuration of offering types, full database-backed and provider E2E acceptance, load/failure/isolation audit. No production readiness certification.
