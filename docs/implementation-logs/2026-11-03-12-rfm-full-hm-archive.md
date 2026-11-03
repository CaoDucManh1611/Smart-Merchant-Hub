# 12 — Full H&M RFM training from the large archive

**Date:** 2026-11-03  
**Delivery:** Local artifacts on `D:\CRM_Industry_Datasets`; no commit or push.

## Dataset inventory finding

The roughly 32.19 GB `archive` directory is the H&M dataset bundle and contains
many product images. The transaction source needed for RFM is
`D:\CRM_Industry_Datasets\archive\transactions_train.csv` (about 3.25 GB). The
images do not contain purchase dates, customer frequency, or transaction spend,
so they were not read.

## Full RFM run

Added `scripts/train_hm_full_rfm.py`, which streams the complete transaction CSV
and aggregates each customer's recency, number of distinct purchase dates, and
monetary sum. It uses the source's chronological date ordering to count unique
customer-day baskets without holding all product baskets in memory. It fitted
the existing `log1p + StandardScaler + MiniBatchKMeans` method with four clusters.

- All 31,788,324 transaction rows were read; 0 invalid rows were skipped.
- Date range: 2018-09-20 to 2020-09-22.
- 9,080,179 customer-day baskets; 1,362,281 customer profiles.
- Cluster sizes: 0 = 683,836; 1 = 171,777; 2 = 199,217; 3 = 307,451.
- Integrity check confirmed profile rows equal the report's customer count,
  frequency sums equal the basket count, and cluster sizes equal the report.

Artifacts:

- `D:\CRM_Industry_Datasets\trained_models\hm\run_20261103_140728_full_rfm\rfm_profiles.csv`
- `D:\CRM_Industry_Datasets\trained_models\hm\run_20261103_140728_full_rfm\rfm_segmenter.joblib`
- `D:\CRM_Industry_Datasets\trained_models\hm\run_20261103_140728_full_rfm\training_report.json`

This full-file run intentionally fits RFM only. The separate H&M next-basket
ranker remains the prior 5-million-row sample; the full 32-million-row ranker
was not fitted in this memory-bounded RFM task.

## Remaining D-drive sources

The other transaction datasets that support standard RFM have been run in
separate artifacts: Dunnhumby, Olist, Online Retail, and Online Retail II.
Retailrocket has no monetary value and was marked RF-only. Expedia lacks
transaction spend, bank marketing is campaign-response data, wholesale is an
annual summary without transaction dates, Yelp is reviews rather than sales,
online-shopping intention has no stable customer purchase history, and Telco
supports churn/value analysis rather than order-based RFM. Those sources should
not be mislabeled as RFM.

All these datasets are public/offline data with source-local identities. No
artifact was loaded into a live shop, and no LightFM or bandit policy was trained.
