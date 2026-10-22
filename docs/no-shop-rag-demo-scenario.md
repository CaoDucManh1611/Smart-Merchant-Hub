# No-shop RAG and media demo scenario

This is a safe rehearsal with **no real shop, social login, customer, or provider send**.

## 1. Run the automated checks

From the repository root in PowerShell:

```powershell
./scripts/run-no-shop-demo.ps1
```

The script runs the isolated no-shop backend/frontend QA, a deterministic RAG routing evaluation, and checks that the synthetic knowledge pack is complete. It clears real provider/API credentials for the test process and restores your shell environment afterwards. It does not start Docker, change a production database, log in to a social network, or send a real customer message.

For the faster backend-only version:

```powershell
./scripts/run-no-shop-demo.ps1 -SkipFrontend
```

## 2. Try retrieval in the app

1. Use a local/demo tenant and open **Kho kiến thức**.
2. Upload these four files individually from `knowledge_base`: profile, product CSV, support policies, and industry playbook. Uploading is opt-in; these files are not seeded into every shop.
3. Wait until the documents show **Sẵn sàng** and inspect the source count/chunks against the current plan.
4. Open **Trợ lý hỏi đáp** and try the cases in `knowledge_base/demo-rag-evaluation.vi-en.jsonl`: pink items, police/customer-neutral support, 12-unit wholesale, out-of-stock item, allergies/skin safety, and an unverified delivery/return question.
5. Check that answers follow the customer's language, cite the right source, check exact product/stock values, do not promise a fake link, and hand off when the pack does not verify safety or policy.

## 3. Test media safely

The composer now shows only media types supported by the selected channel. You can test client-side selection/validation and backend adapter tests without sending anything externally. To do a real delivery test later, use a private test account/channel, an account you control, and a conversation initiated by that test account; confirm the platform's message window/permissions first. TikTok/Shopee are intentionally text-only in this app's current outbound adapters, while Zalo OA is image-only. Do not use real customers for media test messages.

## 4. Reading the learning/RFM results

This pack supplies retrieval examples and demo catalogue traits; it is not a training corpus. RFM and recommendations should be evaluated against synthetic order events/CRM fixtures, not by vectorizing every sale. Check that a new customer has no completed orders, a repeat buyer has earlier completed orders, and cancelled/refunded orders do not falsely create VIP status. Preferences should cite their source and can be corrected or opted out.

Every product price, stock value, discount threshold, and policy in this pack is fictional. Replace them before any customer-facing production use.
