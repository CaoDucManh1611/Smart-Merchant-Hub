# Calendar follow-up service context

## Reproduced issue

- A repeated date/time-only calendar question was routed to the catalog with no service name, producing “không tìm thấy dịch vụ”.
- Shop 7 conversation 7 contained 53 inbound messages. The original service request was message 5052, outside the graph's eight-message prompt history.

## Change

- When a read-only calendar follow-up does not itself name a service or rental, resolve the latest explicit offering reference from up to 200 inbound messages in the same tenant-scoped conversation.
- Keep the short LLM prompt history unchanged; this lookup only supplies the typed catalog matcher with the relevant prior user request.
- Continue to route the result through the read-only calendar path; no request collection, booking, or name collection is started.

## Verification

- Read-only DB inspection confirmed the original Wave Alpha 110 service question exists in the same conversation.
- `python -m py_compile backend/app/services/conversation_graph.py` passed.
- `git diff --check` passed for the changed Python file.
- Restarted the local Compose worker; it became healthy and imported the updated module.
- No test suite was run and no Telegram message was sent.
