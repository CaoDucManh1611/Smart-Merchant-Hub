# RAG cases 21–50: live response fixes

Date: 2026-11-04
Branch: `codex/rag-rfm-all-updates-20261104`

## Input reviewed

Reviewed the Telegram replies supplied for catalog cases 21–30. The replies showed a price comparison falling into a generic product list, a tire question that should ask for fitment details, and internal SKU labels in customer-facing output. Several earlier case fixes are already present on this branch; no live replies for cases 31–50 were included in this update.

## Changes

- Routed comparison language including “rẻ hơn” and “chênh nhau” through the same deterministic, tenant-catalog path used by the answer formatter.
- Price comparisons now answer with the compared product names and current prices; a difference question also gets the exact difference. Unrequested stock counts and long catalog descriptions are omitted from these short answers.
- Routed tire-fitment clarification questions to the deterministic path before the LLM planner, so it asks for the vehicle model/year, current tire size, and wheel position instead of listing candidate tires.
- Added a final tenant-scoped SKU redaction for bare catalog identifiers. Technical specifications that are not the shop's SKU remain visible.

## Verification boundary

- No tests were run and no Telegram message was sent in this update.
- The codebase already has grouped-VND parsing and catalog filtering for `200.000đ` / `100.000đ`; the incorrect values in the supplied replies may come from a running worker that has not loaded this checkout. Restart the backend and worker serving the bot before judging those budget cases again.
- Cases 31–50 still need their live answers to confirm whether any further case-specific failure remains.
- No commit or push was made.
