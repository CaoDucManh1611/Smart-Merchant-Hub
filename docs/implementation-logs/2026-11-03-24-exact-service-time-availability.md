# Exact-time service availability lookup

## Issue

- The read-only calendar path checked the whole requested day and did not parse a time such as “9h tối”. It therefore gave a generic staffing warning even when the requested start time was outside operating hours.

## Changes

- Parse an explicit local time from the original message (`9h tối`, `9h30 tối`, or `21:00`). Ambiguous bare `9h` is not silently interpreted as morning or evening.
- For service appointments, calculate the full requested interval from the service duration and check whether that interval fits inside the shop's configured date-specific or weekly opening windows.
- Query existing appointments for the exact service and overlapping interval when a time is present. Do not expose customer identities.
- If the requested interval exceeds opening hours, state that it cannot be served at that time, explain the service duration and closing time, and suggest the latest start that fits. This is a read-only lookup and does not create a booking or ask for a name.
- If the interval fits opening hours but staff availability is not modeled, report that the calendar has no conflict without claiming that a slot is confirmed, and request staff confirmation.

## Current shop 7 lookup

- Timezone: `Asia/Ho_Chi_Minh`.
- Thursday hours: `08:00–21:30`.
- Service: “thay nhông sên dĩa cho Wave Alpha 110”, duration 120 minutes, price 180,000 VND.
- No active appointment overlapped `05/11/2026 21:00–23:00` at inspection time.
- A 21:00 start would end at 23:00, after closing. The latest start that fits the configured 21:30 close is 19:30.

## Verification

- `python -m py_compile backend/app/services/conversation_graph.py backend/app/services/business_request.py` passed.
- `git diff --check` passed for the changed Python files.
- Restarted the local Compose worker; it became healthy and imported the updated modules.
- No test suite was run and no Telegram message was sent during this change.

## Limit

For times within opening hours, a lack of overlapping appointments does not prove staff capacity because employee shifts are not modeled. The bot must continue to ask shop staff to confirm those times.
