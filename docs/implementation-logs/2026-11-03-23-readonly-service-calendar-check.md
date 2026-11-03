# Read-only service calendar check

## Issue

- A service with a valid price was shown with “đơn vị tính chưa được cấu hình” because service offerings had no per-service billing-unit field and the shop profile did not define a default.
- A follow-up asking whether a date has availability could fall into the request-collection flow and ask for the customer's name, even though the customer only wanted a calendar lookup.
- Date parsing used normalized text, which removes separators such as `/` from `05/11/2026`.

## Changes

- Service offerings now use the explicit unit configured by the shop, or “lần” as a safe service-specific display default. Goods and rental units are unchanged.
- Read-only date availability questions are routed to the catalog/calendar path. The service is resolved from the current message or prior user message in the same conversation.
- The date is parsed from the original message. The calendar query is scoped to the current shop and service and uses the shop timezone.
- The answer distinguishes “no appointment recorded” from “a free slot is confirmed.” When business hours or staff availability are not configured, it says availability cannot be confirmed, optionally asks staff to verify, and explicitly says no booking was created and no name is needed.
- A rental availability follow-up asks for a pickup/return date range and does not query appointment records.

## Shop 7 data checked

- Active service: “thay nhông sên dĩa cho Wave Alpha 110”, 180,000 VND, 120 minutes.
- No appointment records were present for the service at inspection time.
- Shop business hours were empty, and the application has no staff-shift availability model. Therefore the system must not claim that a slot is free based only on the empty appointment list.

## Verification

- `python -m py_compile backend/app/services/conversation_graph.py backend/app/services/business_request.py` passed.
- `git diff --check` passed for the changed Python files.
- Restarted the local Compose worker; it became healthy and imported both changed modules successfully.
- No test suite was run, and no Telegram message was sent during this change.

## Limit

The system can report existing bookings, but cannot confirm an open service slot until the shop configures operating hours and staff availability. The current response safely escalates for manual confirmation without starting a booking.
