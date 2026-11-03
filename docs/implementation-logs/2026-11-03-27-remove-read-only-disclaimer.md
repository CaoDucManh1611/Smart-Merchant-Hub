# Remove redundant read-only disclaimer

## Change

- Removed repetitive “lookup only / no booking / no name needed” wording from calendar and rental-availability replies, as requested.
- The calendar route remains read-only; it does not call the booking workflow or collect customer details.

## Verification

- `python -m py_compile backend/app/services/conversation_graph.py` passed.
- `git diff --check` passed for the changed Python file.
- Restarted the local Compose worker and imported the updated module successfully.
- No tests were run and no Telegram message was sent.
