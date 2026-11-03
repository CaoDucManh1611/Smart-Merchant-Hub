# Recommendation compatibility hard filter

Date: 2026-11-03

## Issue

A recommendation request for a Wave Alpha 110 part returned a Vision 110 air filter. The saved request showed the Vision chunk as the only RAG candidate, normalized to relevance `1.0`, despite much stronger catalog/query overlap for the Wave Alpha chain-and-sprocket set (`0.364` versus `0.091`). The natural-language vehicle model was not being converted into a retrieval constraint.

## Change

- Read active, tenant-scoped compatibility attributes from `recommendation_catalog_entries` and `recommendation_catalog_attributes`.
- When the current query contains a distinctive, contiguous compatibility phrase, map it to the exact matching SKU set. Ignore generic phrases and skip inference for explicit SKU requests, missing catalog tables, unbounded matches, or phrases matching every compatible SKU.
- Pass the inferred SKU set into the existing retrieval hard-filter contract. Retrieval applies the SKU constraint to catalog-mapped chunks before `LIMIT`; recommendation serving receives the same filter so unrelated products cannot re-enter at ranking time.
- Keep current price, availability, and product status sourced from the live product catalog.

## Local evidence

- Shop 7's catalog stores `Honda Wave Alpha 110 ...` compatibility for the Wave Alpha air filter, rear drum brake, and chain/sprocket SKUs. Each has mapped RAG chunks. The Vision filter has separate compatibility text and SKU mappings.
- Python source compilation succeeded in the worker container.
- `git diff --check` passed for the edited service.
- Docker worker restarted and reported healthy.

## Validation limits

No test suite was run. No additional Telegram prompt was sent after the code change, so the live bot answer has not been confirmed. No clicks, quotes, purchases, or synthetic feedback were recorded. No commit or push was made.
