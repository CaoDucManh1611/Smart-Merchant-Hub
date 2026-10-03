# CRM UI Templates Handoff

## Baseline Before Changes

Branch: `feat/crm-ui-templates`, created from a clean `main` worktree.

### Already available

- Product create/edit, inventory, product CSV import preview, and product/order exports are wired in `frontend/src/App.vue`.
- Product import accepts CSV/TXT with SKU and name required; supported fields include English name, description, price, stock, status, category, suitable-for, colors, sizes, and keywords.
- Order import supports preview and creates draft orders. Required CSV columns are `order_number,customer_id,sku,quantity`; `conversation_id` is optional.
- Email OTP flows exist for shop signup and adding staff. They are not a shop-account email-verification settings flow.
- TikTok/Shopee pairing code creation and current channel status listing are available.
- Customer 360 and saved tag-based segments exist. Recommendation-serving and interaction-summary APIs exist, but the current customer UI does not consume them.
- Existing frontend test command is `npm test`; production build command is `npm run build`.

### Missing or blocked by current API contract

- Product schemas and persistence have no dedicated product URL column/field. Product create/update already accepts generic metadata, so `metadata.product_url` can be saved without a backend change.
- No account email OTP configuration/verification endpoint is present in the inspected API. Existing signup/staff OTP APIs cannot be repurposed for settings.
- No screenshot deliverables or import-template usage guide existed at baseline.
- Successful service-plan submissions use inline confirmation rather than an accessible animated confirmation dialog.
- Customer 360 does not yet display RFM segment, recommendation reasons, or known/unknown interaction interests.

## API Contracts Used

- Product template: the import field map in `backend/app/api/sales.py`.
- Order template: `POST /orders/import`, required columns above, draft-only behavior.
- Customer insights: `POST /recommendations` and `GET /recommendations/interactions/summary` response contracts in `backend/app/schemas/recommendation.py`.
- Connector pairing: `POST /onboarding/shops/{business_id}/channels/{channel_type}/pairing-code` and `GET /onboarding/shops/{business_id}/channels`.

## Verification and Evidence

### Delivered

- Product create/edit and inline detail edit now save validated HTTP(S) links under the existing `metadata.product_url` contract. Invalid/unsafe stored values render as an error label, never as an anchor. External links open with `noopener noreferrer`.
- Customer 360 consumes the existing recommendation and interaction-summary APIs. It displays the API segment and item reasons, names observed interests only when events exist, and labels unmapped products as unknown. Errors and loading states are separate from the rest of the customer profile.
- TikTok/Shopee pairing shows the API-provided expiry, retry actions, and backend status. Creating a code only displays the code; “paired” is shown only from `connector_paired` returned by the channel-status API.
- Successful service-plan submission opens a localized accessible dialog with focus return, Tab containment, Escape handling, mobile layout, and reduced-motion support. Login/service promotional copy was shortened.
- Header-only catalog and sales-order CSV templates are linked from their import screens. See [import-templates.md](import-templates.md) for field and import behavior.
- No backend files were modified. No real customer data is in the templates or screenshots.

### Verification

- `npm test`: 206 passed, 0 failed.
- Vite production build: passed. The output reports the existing large-chunk advisory (main JS about 738 kB). A later `npm run build` retry hit `ENOSPC` while npm wrote its log; running Vite directly with the same dependencies passed.
- Pylance/VS Code diagnostics: no errors in touched Vue, JS, CSS, or test files.
- UI screenshots use synthetic `example.test` data. The integrated browser restricted its viewport to approximately 528 x 366; these are mobile/element-crop captures, not desktop viewport certifications.

Screenshots are in `docs/screenshots/`:

- `crm-login-vi.png`
- `crm-product-editor.png`
- `crm-product-list.png`
- `crm-orders-template.png`
- `crm-customer-insights.png`
- `crm-customer-insights-en.png`
- `crm-channels-mobile.png`
- `crm-connector-guide.png`
- `crm-connector-code.png`
- `crm-connector-pairing.png`

### Remaining API Gates

- Account email OTP configuration/verification is not implemented in the UI: the inspected backend exposes OTP for signup and staff creation, but no API for changing/verifying the shop account email. Do not wire those unrelated OTP flows into settings. This needs the agreed Person 1 API contract.
- The recommendation API returns a segment for one customer at a time; the saved-group API has no bulk RFM/interests contract. The profile displays real customer insights, but an RFM/interests rollup in group rows needs a bulk endpoint before it can be added safely.
- Product links are stored through the existing generic metadata API. The product CSV importer does not map a URL column, so links are intentionally absent from the import template and documented as edited in the product form.

### Branch and PR

Changes are on `feat/crm-ui-templates`, based on the clean `main` branch. Commit: `ae27006` (`feat: improve CRM UI templates and insights`); the branch is pushed to `origin`. No merge was performed.

The remote currently has no branch named `integration`/`develop`; `main` is the only shared base branch. The GitHub compare page is [ready to create a PR](https://github.com/CaoDucManh1611/Smart-Merchant-Hub/compare/main...feat/crm-ui-templates?expand=1), but the browser session is signed out and no authenticated PR tool is available, so the PR itself was not submitted. Confirm `main` as the target or publish the intended integration branch first. Keep the email-OTP and group-insight API gates explicit in the PR rather than representing them as complete.