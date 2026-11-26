# Split checkout fragments and missing-contact response — 2026-11-25

- Verified incoming text/card events reached the current shop. The contact-card event carries no usable phone field in its stored provider payload; do not invent a number from an empty attachment.
- Found a debounce boundary loss: an email and the next message were 5.066 seconds apart with a 5-second window. The earlier job deferred merely because any later message existed, but the later batch could not include it. Restrict deferral to a later actionable message inside the same time window, so valid fields are processed instead of dropped.
- Partial retail checkout now uses known name/email context to accept a standalone shipping-address fragment while phone is missing. Existing question/action guards remain in place.
- If a payment choice arrives while required fields remain missing, respond with the missing fields instead of silently waiting. A missing phone is requested as text rather than assuming a contact card was read.
- New regressions cover the 5.066-second boundary, missing-phone card scenario, and complete split name/phone-email-address-COD flow with AI disabled. All 3 new tests passed.
- No live customer data, orders or outbound messages modified by these tests. Current live session had already progressed when inspected, so no historical fragment replay or old-order mutation was performed.

Broader verification: 131 checkout/fragment/worker regression tests passed. Backend and worker restarted after test completion.
