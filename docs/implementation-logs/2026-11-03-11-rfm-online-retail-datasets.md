# 11 — Additional RFM datasets from drive D

**Date:** 2026-11-03  
**Delivery:** Local artifacts on `D:\CRM_Industry_Datasets`; no commit or push.

## Added sources and completed runs

Extended `scripts/train_industry_recommender.py` with streaming Excel workbook
support for UCI Online Retail and Online Retail II. The reader uses `openpyxl`
in read-only mode. The adapters normalize customer/invoice IDs, group products
by invoice, and exclude missing customer IDs, cancelled invoices, and rows with
non-positive quantity or unit price. The workbook inputs were not modified.

| Source | Eligible purchase rows | Baskets | RFM profiles | Holdout next-basket NDCG@5 |
|---|---:|---:|---:|---:|
| Online Retail | 397,884 | 18,532 | 4,338 | 0.934171 |
| Online Retail II | 805,549 | 36,969 | 5,878 | 0.927406 |

Run artifacts:

- `D:\CRM_Industry_Datasets\trained_models\online_retail\run_20261103_140035`
- `D:\CRM_Industry_Datasets\trained_models\online_retail_ii\run_20261103_140123`

Both runs contain `rfm_profiles.csv`, `rfm_segmenter.joblib`,
`next_basket_ranker.joblib`, and `training_report.json`. NDCG is for the
sampled next-basket ranker, not cluster quality or live conversion uplift.

## Other datasets not treated as RFM

- Expedia search/bookings does not provide purchase monetary value.
- Bank Marketing is campaign response data, not customer purchase history.
- Online Shoppers Intention lacks stable transaction-level customer and spend
  history.
- Wholesale Customers is an annual customer/category summary without purchase
  event dates or order frequency.
- Yelp reviews/tips/check-ins are not sales and have no purchase monetary value.
- Telco profiles can support subscription/churn segmentation, but do not contain
  the order history needed for the project's RFM definition.
- `DwnlData\Administrator` contains no usable dataset files.

These can have their own analytics models, but calling them RFM would invent
missing Recency/Frequency/Monetary evidence. Public-data profiles remain offline
benchmarks and are not imported into any live shop.
