# Short-address order form fix — 2026-11-25

- Root cause: the deterministic goods form parser required an unlabelled address to have >=8 characters, while the existing address validator accepts >=5. The supplied abbreviated address was 7 characters, so the whole form was rejected and routed through failing AI calls.
- Aligned unlabelled-address recognition with the existing >=5 validation, preserving numeric/text requirements and excluding order/question commands. No product, quantity, price, payment or order status logic changed.
- Added full-graph regression cases for one multiline form and five individual fragments, with both graph/business-request AI calls explicitly disabled. They preserve quantity 2, reach review, and create no order before confirmation.
- Adjusted existing fixture setup to avoid duplicate email/address definitions already present in current goods defaults.
- 11 targeted order-form, required-shipping and payment-confirmation tests passed.
- Read-only verification against the current failing shop 8 conversation recognized all 5 fields from the actual submitted form. No live contact/session/order data written and no outbound customer messages sent.
- Backend/worker restarted. Customers can resend the form to continue their current pending request; no need to begin another order.
