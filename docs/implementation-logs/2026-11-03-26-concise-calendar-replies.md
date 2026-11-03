# Concise calendar lookup replies

## Change

- Shortened read-only appointment lookup replies to remove duplicate calendar and interval explanations.
- Out-of-hours replies now state the requested time, the closing-time/duration reason, the latest feasible start when one exists, and that no booking or name is needed.
- In-hours replies summarize whether the appointment ledger has a conflict and say staff must confirm capacity.
- Closed-day, missing-hours, and missing-duration replies use similarly concise wording.

## Verification

- `python -m py_compile backend/app/services/conversation_graph.py` passed.
- `git diff --check` passed for the changed Python file.
- Restarted the local Compose worker; it became healthy and imported the updated module.
- No tests were run and no Telegram message was sent.
