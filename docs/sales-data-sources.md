# Sales data for experiments

## Million-row English transaction data

[UCI Online Retail II](https://archive.ics.uci.edu/dataset/502/online+retail+ii) contains 1,067,371 transaction rows from a UK online retailer (2009–2011). It is useful for RFM, basket analysis, and recommendation experiments; it is English/UK-specific and old, not a source of current market prices. The UCI record provides the downloadable workbook and citation/license details. Attribute Daqing Chen and UCI as required by the dataset terms.

## Vietnamese e-commerce interactions

[ViEcomRec](https://doras.dcu.ie/29693/) reports 369,099 Vietnamese e-commerce review/interactions for 2,244 face-cleanser items and 304,708 users. It is below one million rows, is product-category-specific, and its [dataset repository](https://github.com/linh222/face_cleanser_recommendation_dataset) says it is not for commercial use. Use it only if the project/use is allowed by its terms; do not redistribute it as commercial training data.

There is no verified public, licensed dataset linked here that has millions of Vietnamese real order records. Do not scrape private shop conversations or order records to fill that gap.

## Generate a bilingual million-row demo

The included generator is deterministic, requires only Python's standard library, and creates fake data (not real buyers or sales):

```powershell
python scripts/generate_demo_sales_data.py --rows 1000000 --output build/demo_sales_bilingual_1m.csv.gz
```

The compressed CSV includes Vietnamese/English product/category/color fields, fake customer IDs, order dates, channel, quantity, amount, and status. Every row is marked `is_synthetic=true`. Use it to test import, RFM, and ranking pipelines—not to answer factual product/policy questions.

## What belongs in the knowledge base

Use product catalogues, shipping/return/warranty policies, size/color charts, and approved response guides as retrieval knowledge. Keep transactions in structured order tables for RFM and recommendations. Indexing a million raw order lines as RAG text is expensive and can cause the assistant to confuse one customer's order with another's. The `knowledge_base/` folder contains a starter policy and test cases; replace every shop-specific placeholder with verified business information before use.
