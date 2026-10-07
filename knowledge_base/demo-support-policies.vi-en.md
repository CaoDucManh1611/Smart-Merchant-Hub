# Demo support policy and FAQ / Chính sách hỗ trợ demo

> **DEMO DATA — synthetic only.** Replace this entire file with approved shop policy before customer use. Do not present these values as the real shop's policy.

## Delivery / Giao hàng

- Test coverage: Vietnam nationwide, subject to carrier confirmation.
- Test estimate: 2–5 business days after order confirmation. This is only a scenario value, not a carrier promise.
- Test fee: 30,000 VND for orders below 500,000 VND; free shipping at or above 500,000 VND.
- Do not promise an exact arrival time. For an existing order, use the structured order/tracking record instead of this FAQ.
- English: The demo estimate is 2–5 business days. The final carrier status and delivery date must come from the order's tracking record.

## Payment / Thanh toán

- Test methods: cash on delivery (COD) or bank transfer after the customer confirms the order.
- Never invent an account number or ask the customer to send card credentials, passwords, or OTPs in chat.
- English: The demo shop supports COD or bank transfer after order confirmation. Ask staff for the verified payment instructions; never invent bank details.

## Return and exchange / Đổi trả

- Test window: contact the shop within 7 days after delivery.
- Test eligibility: unused item, original tags/packaging, proof of purchase. Eligibility still requires staff review; the assistant must not promise approval or refund.
- Report damaged/wrong items promptly with order number and a photo of the issue. Do not ask for unnecessary identity documents.
- Shipping cost for a return is not specified in this demo policy; ask staff to confirm.
- English: Contact the demo shop within 7 days. Items must be unused with original packaging and proof of purchase. Staff confirms eligibility; no automatic refund is promised.

## Wholesale / Bán sỉ

- Test threshold: 10–29 units of the same eligible SKU may qualify for an 8% demo discount; 30+ units may qualify for 12%.
- Discount is a scenario value, subject to current stock and staff confirmation. It is not combined with another promotion in this demo.
- Ask for SKU and quantity before quoting. Never compute a final order total until stock, tax/fees, shipping, and the applicable promotion are confirmed.
- English: Ask which SKU and quantity. The demo thresholds are 10–29 units (8%) and 30+ (12%), subject to stock and staff approval.

## Product and safety questions / Tư vấn sản phẩm và an toàn

- Product name, demo price, color, and demo stock come only from `demo-products.vi-en.csv` for this test pack.
- Do not transform “demo stock 0” into “coming soon” or a restock date. Say it is unavailable in the demo catalogue and ask staff about alternatives.
- Beauty ingredients, skin compatibility, food allergens, medical effects, electrical compatibility, pet suitability, and warranty duration are not fully specified here. Do not claim safety, diagnosis, certification, compatibility, or warranty coverage without verified source data.
- English: Use the product record for listed attributes. If ingredients, allergens, device compatibility, warranty, or safety are missing, state that they are unconfirmed and hand off.

## Customer care and privacy / Chăm sóc và quyền riêng tư

- Use only conversation and order facts needed to answer the customer. A stated color preference may help rank products; it is not proof of a permanent preference.
- If the customer asks not to remember a preference, stop future extraction and use the product only for the current conversation. Route deletion requests to the shop's privacy workflow.
- A customer's job, including police officer, is not a discount tier, identity-verification trigger, or targeting feature.
- Ask for a human when the policy or record does not answer the question. Keep one complete, natural response instead of sending fragments.

## Test FAQ / Câu hỏi mẫu

**Q: Áo nào màu hồng còn hàng? / Which pink shirts are in stock?**
Use the CSV. For this snapshot, DM-APP-001 is pink and has demo stock 24; give its demo price 199,000 VND and clearly call the link a placeholder in the test environment.

**Q: Tôi là công an, shop có ưu tiên không? / I'm a police officer; do I get priority?**
No occupation-based priority is defined. Offer the normal support process and answer the actual product/order question.

**Q: Tôi muốn nhập 12 cáp USB-C. / I want to wholesale 12 USB-C cables.**
Identify DM-ELE-001; the demo policy's 10–29-unit tier is 8%, but confirm stock and staff approval before promising a final quote.

**Q: Sản phẩm có an toàn cho da nhạy cảm không? / Is this safe for sensitive skin?**
No verified safety claim is included. Share only listed ingredients if another approved product source has them; otherwise hand off.

## Extended policy reference / Tra cứu chính sách mở rộng

The following entries repeat the same demo rules in question-oriented form so retrieval can find the relevant answer from natural customer wording. They do not add new guarantees.

### Delivery questions / Câu hỏi giao hàng

**Can the shop guarantee delivery tomorrow? / Shop bảo đảm mai giao tới không?**

No exact delivery date is guaranteed. The 2–5 business-day range is only an estimate after order confirmation; check the carrier record for an existing order.

**Can I get same-day or express delivery? / Có giao hỏa tốc trong ngày không?**

Same-day and express options are not specified in this demo policy. Ask staff to check availability and fee before promising anything.

**How much is shipping for a 300,000 VND order? / Đơn 300.000 đồng phí giao hàng bao nhiêu?**

The demo policy lists a 30,000 VND fee below 500,000 VND. This is a sample rule only; the final fee still needs to be checked for the destination and order.

**Is shipping free for a 500,000 VND order? / Đơn 500.000 đồng có miễn phí ship không?**

The demo threshold is free shipping at 500,000 VND or above. Confirm eligible items, destination, and final payable amount in the order flow.

**Where is my package now? / Đơn của tôi đang ở đâu?**

Do not answer from this policy. Look up the signed-in customer's structured order/tracking record. Ask for the minimum order reference needed if no matching record is found.

### Payment questions / Câu hỏi thanh toán

**Can I pay by card, e-wallet, or split payment? / Có thể trả thẻ, ví điện tử hoặc trả góp không?**

These methods are not listed in the demo policy. Do not say they are accepted; ask staff to verify.

**I transferred money; has the shop received it? / Tôi chuyển khoản rồi, shop nhận chưa?**

Only a confirmed payment record can establish receipt. Do not infer success from a screenshot or ask the customer to disclose a password, OTP, or full card number.

**I was charged twice. / Tôi bị trừ tiền hai lần.**

Apologize, avoid promising a refund, collect only the order/reference needed, and hand off for payment reconciliation.

**Can you send me the bank account number here? / Gửi tôi số tài khoản ở đây được không?**

The demo has no bank account number. Do not invent one; route the customer to verified staff instructions.

### Returns, exchanges, and refunds / Đổi hàng và hoàn tiền

**The item arrived damaged. What should I do? / Hàng bị hỏng khi nhận thì làm sao?**

Ask for the order reference and a photo of the issue, then hand off for review. Do not promise replacement or refund before staff confirms eligibility.

**I removed the tag or opened the package. Can I return it? / Tôi tháo tem hoặc mở hộp rồi có trả được không?**

The demo eligibility requires an unused item with original tags/packaging and proof of purchase. Staff must review the actual case; the assistant must not approve or reject it automatically.

**Who pays return shipping? / Phí gửi hàng trả lại ai chịu?**

This is not specified. Say so and ask staff to confirm; do not assume that either party pays.

**When will I receive a refund? / Bao lâu được hoàn tiền?**

No refund timing is specified and no automatic refund is promised. A staff member must confirm eligibility and the payment workflow.

**Can I cancel after the order was packed? / Đơn đóng gói rồi có hủy được không?**

The demo policy does not define a cancellation cutoff. Check the actual order state and hand off; do not mark it cancelled unless the CRM confirms the change.

### Wholesale and quotation questions / Bán sỉ và báo giá

**What is the discount for 5 units? / Mua 5 món giảm bao nhiêu?**

No wholesale discount threshold is listed for fewer than 10 units. Do not extrapolate; ask staff whether another approved promotion applies.

**What is the discount for 29 units? / Mua 29 món giảm bao nhiêu?**

The demo tier is 8% for 10–29 units of the same eligible SKU, subject to stock and staff approval. This is not a confirmed quote.

**What is the discount for 30 units? / Mua 30 món giảm bao nhiêu?**

The demo tier is 12% for 30 or more units of the same eligible SKU, subject to stock and staff approval. Confirm SKU, quantity, fees, and final total first.

**Can I combine wholesale and another sale? / Có cộng dồn với khuyến mãi khác không?**

The demo wholesale policy says the bulk discount is not combined with another promotion. Staff must confirm the eligible SKU and final terms.

**Can you issue a company invoice or quotation? / Có xuất hóa đơn công ty hoặc báo giá không?**

The demo policy does not define invoice or quotation requirements. Collect the business need and route it to staff; do not promise tax treatment or document issuance.

### Service, support, and privacy / Dịch vụ, hỗ trợ và quyền riêng tư

**Can I book tomorrow afternoon? / Chiều mai còn lịch không?**

The catalogue marks the service as requiring schedule confirmation. Check live availability; a question or draft request is not a confirmed booking.

**What are the shop's support hours? / Giờ hỗ trợ của shop là khi nào?**

Support hours are not specified in this demo policy. Do not invent business hours; ask staff or use a verified current schedule.

**Please forget my color preference. / Đừng lưu sở thích màu sắc của tôi.**

Stop future extraction of that preference and follow the shop's privacy workflow for deletion. Do not claim deletion is complete until the system confirms it.

**Why do you need my password or OTP? / Sao cần mật khẩu hoặc OTP của tôi?**

The shop must never request a password, one-time code, or full payment-card credentials in chat. If a workflow appears to ask for these, stop and hand off.

## Source precedence / Thứ tự ưu tiên nguồn

1. Current structured CRM order/payment/inventory record for a specific transaction.
2. Current shop-approved product catalogue for SKU, price, stock, and product attributes.
3. Current shop-approved policy for delivery, payment, returns, wholesale, and support.
4. This fictional policy only for this isolated demo tenant.

If a live record and a written policy conflict, do not silently resolve the conflict. State that staff needs to verify it and hand off.
