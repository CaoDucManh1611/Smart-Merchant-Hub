# RAG playbook for a multi-industry CRM / Cẩm nang RAG CRM đa ngành

> This is a response-quality guide, not a source of product facts, professional advice, or substitute industry policy. Each tenant should upload its own approved catalogue, service scope, safety information, pricing, and escalation rules.

## Retrieval boundaries

- **RAG documents**: approved policies, product descriptions, service scope, warranty/return rules, store FAQs, internal support guides.
- **Structured CRM data**: live price and inventory, order status, customer identity, conversation assignment, appointments, and sales events.
- **Customer features**: keep tenant-scoped and explainable. Store an extracted preference only when supported by explicit text or repeated behavior, with source message, confidence, last observed date, and opt-out handling.
- **Analytics**: aggregate RFM and co-purchase statistics from order tables; do not embed every order or raw chat as a knowledge document.
- If two sources disagree, prefer the newest verified shop source and disclose uncertainty; never silently choose an unsupported number.

## Recommendation behavior

1. Resolve the product request first: product type/use, budget, size/model, and quantity when relevant.
2. Rank in-stock items matching explicit preferences (for example, pink color) before broader alternatives. Use color, category, size, brand, and use-case only when available in structured catalogue or a cited shop source.
3. Treat purchase history as evidence with strength, not identity: one purchase is weak; repeated recent purchases are stronger; an explicit “I like pink” is stronger still. Preferences can expire or be corrected.
4. Do not infer sensitive traits or target a person from occupation, health, religion, political views, legal status, or protected characteristics. An occupation mentioned casually is not a marketing segment.
5. Explain briefly why each item matches and limit the first answer to a few options. Verify stock and price immediately before quoting.

## RFM and customer labels

- Calculate recency from the latest completed, non-refunded sale; frequency from distinct completed orders; monetary value from net paid value after refunds/discounts.
- Define thresholds per tenant/industry and recalculate on a documented schedule. Do not apply a universal spending cutoff across unrelated sectors.
- “Khách mới / New” means no prior completed order. “Khách quay lại / Returning” means at least one earlier completed order and a more recent one. “Khách quen / Regular” and “VIP” require explicit tenant thresholds and sufficient history.
- Keep operational labels separate from AI guesses. Display the reason (e.g. “3 completed orders in 90 days”) and allow staff correction.
- Avoid promoting a customer to VIP based only on a chat, a large unconfirmed cart, or a canceled/refunded purchase.

## Industry-specific checks

### Fashion, beauty, home, and electronics retail

Use SKU, live stock, exact color/size/model, price, and product link. Ask a concise clarifying question for device compatibility, size, material, ingredient, warranty, or safety details missing from the source.

### Food, supplements, and personal care

Do not infer allergy safety, nutrition, diagnosis, treatment, certification, or efficacy from a product name. Require verified label/specification and route uncertain safety questions to a human.

### Wholesale and B2B shops

Collect SKU, quantity, delivery area, and requested date. Quote only an approved price tier and confirmed stock. Never fabricate a bulk discount or tax/shipping calculation.

### Services, appointments, and project work

Use the configured service scope, availability, cancellation rules, and assigned staff. A quote or appointment is not a confirmed booking until the CRM workflow says it is confirmed.

### Shops serving professional customers

Answer the commercial request using the same published policy for everyone. Do not request proof of occupation unless a documented legal/workflow requirement says it is necessary; this guide does not define such a requirement.

## Natural multi-message replies

- When a customer sends several short messages in quick succession, the conversation layer may buffer them briefly, then answer the combined intent once.
- Preserve message order and separate distinct requests. If a required detail is missing, ask one focused question rather than making several guesses.
- Return one human-sounding answer, not model tokens, markdown debris, repeated product dumps, or sentence fragments. Keep citations/source details internal unless the product UI intentionally exposes them.
- Do not split a single answer into separate sends solely because retrieval returned several chunks.

## English response guardrails

Respond in the customer's latest language. For English: state what is verified, call out what is not confirmed, then give the next step. Do not translate placeholder values into a real offer.

## Retrieval cards by request type / Thẻ truy xuất theo loại câu hỏi

These cards help keep facts in the right source. Product records remain in the CSV; the cards describe how to retrieve and respond, not extra product guarantees.

| Customer request | Primary source | Required check | Safe next step if missing |
|---|---|---|---|
| Exact price or stock | Live catalogue; demo CSV only in this test | SKU, current price, quantity | Say it needs checking; do not quote a cached value as current |
| Color, size, or model | Product record | Exact variant, not only the family name | Ask which variant/model they mean |
| Delivery estimate | Shop policy | Confirmed order and destination; for existing orders use tracking | Avoid exact arrival promises |
| Existing order or payment | Authenticated CRM record | Match customer and order; verify current state | Ask for the order reference or hand off |
| Return, refund, or cancellation | Current policy plus order state | Time window, item condition, recorded status | Staff review; never claim completed action prematurely |
| Wholesale price | Approved tier and current catalogue | Same SKU, quantity, stock, promotion conditions | Ask SKU/quantity and request staff approval |
| Safety or compatibility | Verified label/specification | Exact ingredient, allergen, device/model, or use | Stop claims and hand off |
| Appointment or service quote | Service scope and live calendar | Service, time, assigned staff, approval state | Create a request, not a confirmed booking |

## Product-family discovery examples / Ví dụ gợi ý theo nhóm hàng

The associations below are **demo merchandising ideas**, not observed sales or proven co-purchases. Use them only when relevant and in stock. For production, replace this section with the shop's approved catalog relationships or measured order-line data.

### Apparel and accessories / Thời trang và phụ kiện

- Start with the requested garment and exact color/size; use `DM-APP-001` for the pink basic shirt example.
- If the shopper asks for a matching carry item, the pink tote `DM-APP-003` is a possible related suggestion; state that it is a separate item and confirm stock.
- The hair clip `DM-APP-005` is an optional low-cost accessory suggestion only when the customer asks for styling or add-ons. Do not pad a simple answer with unrelated products.
- The beige canvas tote `DM-APP-004` has zero demo stock. Do not recommend it as available or invent a restock date.

### Beauty and personal care / Làm đẹp và chăm sóc cá nhân

- Separate cosmetic accessories from skincare products: a pouch or headband is not a cosmetic treatment.
- For cleanser or moisturizer questions, retrieve only the listed size/ingredients. This demo pack contains no verified clinical outcomes, allergy profile, or suitability guarantee.
- Ask about customer-stated preference or requested use; do not infer a condition from a product click or purchase.

### Electronics / Điện tử

- Match connector type, wattage, model, and included components before recommending a cable or charger.
- The demo USB-C cable does not include a charger. A related charger can be mentioned only as a separate item and device compatibility must be checked.
- The phone case is limited to the device model printed on its package. Ask the model before quoting compatibility.
- Do not claim a product supports fast charging, a particular device, or a warranty unless the record states it.

### Home, food, pets, and stationery / Nhà cửa, thực phẩm, thú cưng và văn phòng phẩm

- Match dimensions, capacity, cleaning method, and use environment for home goods. Do not imply microwave/dishwasher safety unless explicitly listed.
- Food ingredients and allergen labels must be checked on the exact batch. The sample sesame cookie row requires label confirmation and must not be called allergen-free.
- For pet products, ask for relevant size or clip compatibility if not listed; never make veterinary claims.
- For stationery, confirm paper size, page count, ink color, and tip size from the catalogue before answering.

### Services and B2B / Dịch vụ và khách doanh nghiệp

- A listed service is not a confirmed reservation. Check the live calendar and state whether the request is pending or confirmed.
- For a bulk quotation, collect SKU, quantity, delivery destination, and requested date. Apply only the demo tiers in the policy and mark them subject to approval.
- If a request involves a company invoice, taxes, contract, integration, or service scope not documented in the tenant's approved source, route it to a staff member.

## Customer preference evidence / Độ tin cậy sở thích

Use a documented human handoff (also called a `handoff`) whenever safety, privacy, policy approval, or an uncertain commercial decision needs staff review.

Keep separate signals instead of storing a single permanent label:

1. **Current request:** “show me pink items” applies to the current answer only.
2. **Explicit preference:** “I usually prefer pink” may be saved if consent and retention rules permit; store the source, date, and confidence.
3. **Repeated behavior:** several completed purchases can add evidence, but use completed/non-refunded order lines and avoid inferring from a one-off gift or return.
4. **Correction or opt-out:** a customer's correction overrides a weaker inference. A request not to remember must stop future extraction and use the product privacy workflow.

Do not infer gender, age, income, occupation, health, religion, or legal status from color, category, or purchase behavior. Do not use those traits to rank offers.

## Suggested short response patterns / Câu trả lời mẫu ngắn

**Known product fact:** “Áo thun Mây Basic màu hồng đang có 24 sản phẩm trong dữ liệu demo, giá mẫu 199.000₫. Đây là tồn kho giả lập; mình có thể kiểm tra bản ghi hiện tại của shop nếu bạn đang dùng shop thật.”

**Missing product qualifier:** “Mình kiểm tra được ốp theo mẫu máy. Bạn đang dùng model điện thoại nào?”

**Policy not specified:** “Chính sách mẫu chưa ghi rõ bên nào chịu phí gửi trả. Mình chuyển nhân viên xác nhận để không báo sai nhé.”

**Sensitive safety question:** “Nguồn hiện tại chưa xác nhận sản phẩm phù hợp với dị ứng đó. Bạn đừng dùng dựa trên suy đoán; mình nhờ nhân viên kiểm tra nhãn thành phần giúp bạn.”

**English equivalent:** “I can't verify that from the current product record. Please share the exact model/label, or I can ask a staff member to confirm.”

## Negative retrieval checks / Trường hợp cần tránh

- A general delivery estimate must not override a live order tracking status.
- A product title containing “pink” must not override a conflicting structured `color` value.
- A zero-stock item must not be described as available because similar items are in stock.
- A wholesale threshold must not be applied to mixed SKUs unless the policy explicitly allows it.
- An old conversation, test customer, or another tenant's record must never be used to answer a current customer's private order question.
- A retrieved document is evidence for an answer, not authorization to issue a refund, change payment state, cancel an order, or confirm an appointment.
