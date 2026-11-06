# RAG live retest: selected cases 23, 25, 26, 35, 47, 50

Date: 2026-11-04  
Branch: `codex/rag-rfm-all-updates-20261104`

## Telegram retest through the Codex browser

| Case | Live result |
| --- | --- |
| 23 | Correctly lists 10 lowest-priced items under 200,000 VND and discloses 18 matches in total. |
| 25 | Correct: each M10 mirror is 115,000 VND; stocks 21 and 18; total 230,000 VND. |
| 26 | Correct: chain set 465,000 VND plus chain spray 105,000 VND; total 570,000 VND. Uses the live catalog values. |
| 35 | Failed: included long tire descriptions and stock counts, and omitted the 50,000 VND price difference. |
| 47 | Correct: service labor is 180,000 VND per visit and estimated at 120 minutes; no unsolicited calendar question. |
| 50 | Product names, prices (118,000 and 325,000 VND), and available stock (17 and 10) were correct. The compatibility caveat was damaged by the SKU-label sanitizer. |

## Code changes

- Tire-size comparisons now return the two current prices and their difference without unrelated stock counts or long descriptions.
- Narrowed SKU-label matching so ordinary Vietnamese wording such as “mã phụ tùng cũ” survives customer-facing cleanup. Exact tenant-owned catalog SKUs remain redacted.

## Verification

- Targeted regression checks: **2 passed, 63 deselected**.
- Backend and worker were restarted to load the updated code and reported healthy.
- Telegram replies above were collected before the final two code changes; those two changes were not rechecked live in this run.
- No commit or push was made.
