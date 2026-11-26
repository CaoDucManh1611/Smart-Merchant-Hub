# Shop 8 shipping collection correction — 2026-11-25

Observed order CHAT-11 used configurable business-request goods collection, whose persisted configuration contained only name, phone and quantity. This is a second goods checkout path, not the five-field retail form. Payment method was appended at runtime, but shipping address and email were never required.

Changes:
- Shop 8 goods collection now includes name, phone, email, address and quantity. Service/rental configuration unchanged.
- Default goods profile now includes email and shipping address for newly configured shops. Explicit shop configurations remain authoritative.
- Saved prior shop configuration under backups/shop8-business-profile-before-shipping-20261125.json. Repeatable update script: scripts/fix_shop8_shipping_fields.py.
- Tests: 2 new shipping tests passed, including refusal to reach review/create order without address/email; 7 service/rental tests passed.
- Backend/worker restarted to load defaults. No historical order edited and no outbound message sent in this task. CHAT-11 remains as previously created; its missing address must be obtained from the customer, not invented.

QR status remains partial: payment text/link is delivered through the previous fallback, but Zalo still rejects direct image delivery. This task does not claim the QR-image issue resolved. See zalo-payment-qr-20261125.md.
