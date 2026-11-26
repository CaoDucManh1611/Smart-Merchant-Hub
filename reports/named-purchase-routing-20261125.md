# Explicit named purchase routing — 2026-11-25

- Reproduced the exact customer sentence with and without prior product history while remote interpretation was disabled. Both failed before the fix.
- Root causes: broad discovery detection treated `muốn mua ... màu` as browsing, so the explicit purchase did not enter checkout; the catalogue interpreter could also block a uniquely grounded purchase on remote API failure.
- Removed `muốn mua` as a blanket discovery trigger. Generic product browsing questions still use existing generic-word/question guards. Added a unique-current-product purchase pass-through before remote catalogue interpretation, preserving price/stock/basic budget handling and existing transaction checks.
- Exact-sentence regression now quotes 2 Son dưỡng môi không màu at 59000 each, total 118000, preserves product ID and quantity, creates no order before confirmation, and requires no AI call.
- 25 targeted named-purchase/lip/price/basic catalogue tests passed. Broader checkout/form/stock regression suite is run separately.
- Backend/worker restarted. No live message sent, no real order or customer data changed.

Broader verification: 147 checkout/form/catalogue/stock tests passed. Backend /health 200; backend and worker healthy.
