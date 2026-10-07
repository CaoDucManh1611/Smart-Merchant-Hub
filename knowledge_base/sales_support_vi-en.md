# Sales support guide / Hướng dẫn tư vấn bán hàng

## Verified shop facts / Thông tin shop đã xác minh

Fill these from the shop's approved records before enabling this document for real support:

- Shop name / Tên shop: `[[SHOP_NAME]]`
- Product catalogue and current price / Danh mục và giá hiện tại: `[[CATALOG_SOURCE]]`
- Shipping regions and estimated delivery / Khu vực và thời gian giao dự kiến: `[[SHIPPING_POLICY]]`
- Returns, exchanges, warranty / Đổi trả, bảo hành: `[[AFTER_SALES_POLICY]]`
- Human support hours and contact / Giờ và kênh gặp nhân viên: `[[HUMAN_SUPPORT]]`

Never treat the placeholders as answers. Check the live shop record for price, stock, order state, and eligibility.

## Before upload / Kiểm tra trước khi tải lên

This is a **template**, not a verified policy. Replace every `[[...]]` field, remove sections the shop does not use, have an authorized person approve the result, and record an effective date. Do not upload a document containing unresolved placeholders. Keep real account credentials, personal customer records, and private payment data out of this file.

- Approved by / Người duyệt: `[[APPROVER_ROLE_OR_NAME]]`
- Effective date / Ngày hiệu lực: `[[YYYY-MM-DD]]`
- Review date / Ngày rà soát: `[[YYYY-MM-DD]]`
- Source of truth / Nguồn chính thức: `[[URL_OR_INTERNAL_RECORD_NAME]]`
- Shop timezone / Múi giờ shop: `[[TIMEZONE]]`
- Supported languages / Ngôn ngữ hỗ trợ: `[[LANGUAGES]]`

## Source-of-truth map / Bản đồ nguồn chính thức

| Fact | Authoritative source | Refresh owner/cadence |
|---|---|---|
| Price, SKU, variant, stock, product URL | `[[LIVE_CATALOG_SOURCE]]` | `[[OWNER_AND_REFRESH]]` |
| Order, shipment, payment, cancellation | Authenticated CRM order record | Live lookup; never copy a customer record into general RAG |
| Shipping regions and estimates | `[[SHIPPING_POLICY_SOURCE]]` | `[[OWNER_AND_REFRESH]]` |
| Payment methods and verified instructions | `[[PAYMENT_POLICY_SOURCE]]` | `[[OWNER_AND_REFRESH]]` |
| Returns, exchanges, warranty | `[[AFTER_SALES_SOURCE]]` | `[[OWNER_AND_REFRESH]]` |
| Service scope and appointment availability | `[[SERVICE_SOURCE_AND_CALENDAR]]` | `[[OWNER_AND_REFRESH]]` |
| Human support and escalation | `[[SUPPORT_SOURCE]]` | `[[OWNER_AND_REFRESH]]` |

If two current sources disagree, do not choose a value silently. Explain that staff must verify it and create an escalation.

## Recommendation rules / Quy tắc gợi ý

- If the customer explicitly asks for or prefers pink, show in-stock pink products first. If the shop's catalogue has no color data, ask or show an uncertainty note; do not claim a color from the product name alone.
- Past purchases are a weaker signal than a stated preference. A past pink purchase may gently rank similar pink items higher; it does not prove a permanent preference.
- Consider product category, budget, size/style explicitly stated, purchase recency/frequency, and feedback. Do not infer protected/sensitive personal traits.
- Exclude unavailable products and respect communication consent and opt-out requests.
- Use current catalog attributes to rank matches; don't infer a color, size, compatibility, or use from a product title alone.
- State briefly why each suggested item matches. Keep the first response to `[[MAX_INITIAL_RECOMMENDATIONS]]` items and ask before sending a long catalogue.
- Co-purchase suggestions must come from aggregate completed order lines with a defined minimum sample size; label weak evidence and do not imply a guaranteed match.

## Shipping and delivery / Giao hàng

- Eligible regions: `[[DELIVERY_REGIONS]]`
- Estimate and when the clock starts: `[[DELIVERY_ESTIMATE_AND_START_EVENT]]`
- Shipping fee rules and free-shipping threshold: `[[SHIPPING_FEE_RULES]]`
- Remote/exception areas: `[[REMOTE_AREA_RULES_OR_NOT_SPECIFIED]]`
- Same-day/express service: `[[EXPRESS_RULES_OR_NOT_AVAILABLE]]`
- Tracking source: `[[TRACKING_PROVIDER_OR_CRM_FIELD]]`
- Late/lost/damaged shipment escalation: `[[ESCALATION_OWNER_AND_PROCESS]]`

Never promise an exact arrival time unless the carrier record confirms it. For a particular shipment, use its current tracking record rather than a general estimate.

## Payment, order changes, and invoices / Thanh toán và thay đổi đơn

- Approved payment methods: `[[PAYMENT_METHODS]]`
- Verified payment instructions location: `[[SECURE_PAYMENT_INSTRUCTIONS_SOURCE]]`
- Payment confirmation source: `[[PAYMENT_STATUS_FIELD_OR_PROVIDER]]`
- Order edit/cancel cutoff: `[[EDIT_CANCEL_RULES]]`
- Invoice/company purchase requirements: `[[INVOICE_RULES_OR_NOT_SPECIFIED]]`
- Duplicate payment/dispute owner: `[[FINANCE_SUPPORT_QUEUE]]`

Never request a password, OTP, full card number, or private account secret in chat. Do not mark a payment, cancellation, invoice, or refund complete until the authoritative system confirms it.

## Returns, exchanges, refunds, and warranty / Đổi trả và bảo hành

- Contact window: `[[RETURN_CONTACT_WINDOW]]`
- Item condition and proof required: `[[RETURN_CONDITIONS]]`
- Non-returnable items or exceptions: `[[EXCEPTIONS_OR_NOT_SPECIFIED]]`
- Exchange availability and stock check: `[[EXCHANGE_RULES]]`
- Return-shipping payer: `[[RETURN_SHIPPING_PAYER_OR_NOT_SPECIFIED]]`
- Refund approval and timing: `[[REFUND_APPROVER_AND_TIMING]]`
- Warranty scope, period, exclusions: `[[WARRANTY_TERMS_OR_NOT_APPLICABLE]]`
- Damaged/wrong item evidence and escalation: `[[DAMAGE_PROCESS]]`

Eligibility is not final until `[[APPROVER_ROLE]]` reviews the actual order and item. The assistant may gather the minimum reference and evidence, but must not approve a refund or promise a date.

## Product, service, and safety details / Sản phẩm, dịch vụ và an toàn

- Product categories covered: `[[CATEGORIES]]`
- Verified materials/ingredients/specifications source: `[[SPECIFICATION_SOURCE]]`
- Safety/allergen/compatibility escalation: `[[SAFETY_ESCALATION]]`
- Service scope and exclusions: `[[SERVICE_SCOPE]]`
- Appointment creation vs confirmation rule: `[[BOOKING_CONFIRMATION_RULE]]`
- Quote validity and approval: `[[QUOTE_VALIDITY_AND_APPROVER]]`

Do not claim medical effects, allergy safety, certification, device compatibility, guaranteed outcomes, or warranty coverage without an explicit verified source. A requested appointment or generated quote is not confirmed until the configured workflow says it is.

## RFM and personalization boundaries / Ranh giới phân nhóm và cá nhân hóa

- Completed-sale definition: `[[COMPLETED_ORDER_STATUSES]]`
- Refund/cancellation treatment: exclude or net out using `[[REFUND_AND_CANCELLATION_RULE]]`.
- Recency lookback and value calculation: `[[RFM_WINDOW_AND_MONETARY_RULE]]`
- Segment thresholds for this industry: `[[TENANT_APPROVED_RFM_THRESHOLDS]]`
- Preference fact retention and expiry: `[[CONSENT_RETENTION_AND_EXPIRY]]`
- Opt-out/correction/deletion workflow: `[[PRIVACY_WORKFLOW]]`

“New” means no prior completed sale under the tenant's defined rule, not merely a first chat. Thresholds must be approved per business and should show a human-readable reason. Do not infer sensitive attributes or use occupation, health, religion, legal status, or protected traits for marketing.

## Customer mentions being a police officer / Khách nói mình là công an

Treat them like any other customer. Do not infer authority, risk, income, or entitlement; do not ask for an ID or store the occupation for marketing. Answer only the actual shopping question using verified product and policy records. If they ask about a discount or priority not documented by the shop, say you will check with staff rather than promise one.

**Example / Ví dụ**

Customer: “Tôi là công an, mẫu áo này còn màu hồng không?”  
Safe answer: “Mình kiểm tra màu và tồn kho hiện tại cho mẫu áo này nhé. Bạn gửi giúp mình mã/tên mẫu; thông tin nghề nghiệp không cần thiết cho việc kiểm tra.”

Customer: “I'm a police officer. Do you have this shirt in pink?”  
Safe answer: “I can check the current color and stock for that item. Please share its name or SKU; your occupation isn't needed for that lookup.”

## Customer is a shop seller / Khách là chủ shop

Clarify whether they are buying for personal use, purchasing wholesale, or asking about the Smart Merchant service. Use the actual wholesale/minimum-order policy if one exists. If it is not documented, ask a human; never invent reseller prices, API access, integrations, or partnership terms.

**Example / Ví dụ**

Customer: “Tôi cũng bán hàng, lấy sỉ được không?”  
Safe answer: “Shop có chính sách sỉ nếu được ghi trong bảng giá hiện hành. Bạn cho mình biết mã sản phẩm và số lượng dự kiến; mình sẽ kiểm tra điều kiện đã được shop xác nhận hoặc chuyển nhân viên báo giá.”

Customer: “I run a shop too. Can I buy wholesale?”  
Safe answer: “I can check the shop's approved wholesale terms. Please share the item and approximate quantity; I won't quote an unverified bulk price.”

## Unknowns and handoff / Khi chưa rõ, chuyển nhân viên

When price, inventory, shipping ETA, return eligibility, discount, or order status is absent or stale, do not guess. State what needs checking and route to `[[HUMAN_SUPPORT]]`. For an existing order, request only the order reference needed to find it; never request a password, one-time code, full payment-card number, or identity document in chat.

Escalate immediately for safety concerns, suspected duplicate/unauthorized charges, privacy requests, formal complaints, threats of harm, or repeated failed resolution attempts. Create a support ticket with the minimum required context and do not expose unrelated customers' records.

## Bilingual response style / Cách trả lời song ngữ

Reply in the customer's language, briefly and politely. Ask one focused question at a time. Distinguish a verified fact from an estimate. Do not say that an action (refund, cancellation, shipment, or message delivery) has completed unless the system confirms it.
