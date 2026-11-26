# Quote approval preserves stock counteroffer quantity — 2026-11-25

- A short approval such as Xác nhận đặt hàng was lexically resolved as a product mention before approval handling; the default quantity 1 could overwrite an accepted stock counteroffer.
- Standalone approval phrases now bypass additional-product matching inside an existing quote. Named purchases/corrections remain on their previous product-edit path.
- Added accept-counteroffer → approval regressions for Xác nhận đặt hàng / Xác nhận / Đồng ý đặt hàng. Assert original SKU, accepted quantity, total, contact form, and no premature order creation.
- Customer example should preserve 18 clay masks at 79000 = 1422000 and continue contact collection.
- No live order, quote session, payment or customer message changed by tests.

Verification: 114 counteroffer/checkout/product-edit regression tests passed.
