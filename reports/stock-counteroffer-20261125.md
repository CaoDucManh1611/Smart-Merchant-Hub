# Stock counteroffer fix — 2026-11-25

- Root cause: insufficient-stock reply returned without saving the proposed product and available quantity; subsequent acceptance fell back to unrelated intent/product routing.
- Persist a single-product stock offer in the existing customer collection session. Prioritize acceptance of that offer before generic catalogue interpretation.
- Recheck availability at acceptance; show an updated offer or out-of-stock response when stock changes.
- Acceptance produces a quote only; existing confirmation/contact collection remains responsible for subsequent checkout. No stock reservation or order is created by accepting the offer.
- Preserve stateless price-only enquiries and cancellation behavior.
- Validation: 145 targeted regression tests passed; then 11 stock-offer tests passed including full graph with AI interpretation disabled, follow-up contact form, reduced availability, sold out, cancellation and price-only enquiry.
- Backend and worker restarted. No customer messages sent; no existing orders or inventory changed. Live-channel delivery has not been tested.
