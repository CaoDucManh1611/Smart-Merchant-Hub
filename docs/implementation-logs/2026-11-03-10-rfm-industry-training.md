# 10 — Offline RFM training from industry datasets

**Date:** 2026-11-03  
**Delivery:** Local artifacts on `D:\CRM_Industry_Datasets`; no commit or push.

## Runs

All runs used `scripts/train_industry_recommender.py`. Each source was processed
independently. RFM profiles and a four-cluster `log1p + StandardScaler +
MiniBatchKMeans` segmenter were saved per source.

| Source | Events | Baskets | RFM profiles | Monetary | Next-basket holdout NDCG@5 |
|---|---:|---:|---:|---|---:|
| Dunnhumby | 2,595,732 (complete) | 276,484 | 2,500 | Yes | 0.900586 |
| H&M | 5,000,000 (capped sample) | 1,505,237 | 614,160 | Yes | 0.763224 |
| Olist | 110,197 (complete) | 96,478 | 93,358 | Yes | 0.440386 |
| Retailrocket | 22,457 transaction events | 17,672 | 11,719 | No; RF-only input | 0.752336 |

Artifacts are in:

- `D:\CRM_Industry_Datasets\trained_models\dunnhumby\run_20261103_135427`
- `D:\CRM_Industry_Datasets\trained_models\hm\run_20261103_135618`
- `D:\CRM_Industry_Datasets\trained_models\olist\run_20261103_135439`
- `D:\CRM_Industry_Datasets\trained_models\retailrocket\run_20261103_135451`

Each run contains `rfm_profiles.csv`, `rfm_segmenter.joblib`,
`next_basket_ranker.joblib`, and `training_report.json`. Profile CSV row counts
were checked against the reports, and all four runs contain four populated
cluster IDs.

## Interpretation and limits

- The cluster IDs are mathematical segments, not validated business labels such
  as “VIP” or “at risk”. Monetary scales and customer behavior differ by source;
  do not merge profiles across industries.
- H&M used the first 5 million rows to stay within a practical local training
  budget; its report records `event_limit_reached: true`.
- Retailrocket has no purchase amount, so its segmenter uses recency and
  frequency only and is not complete RFM.
- The NDCG figures evaluate a separate offline next-basket ranker against
  sampled unobserved products. They are not an evaluation of cluster quality,
  CRM conversion uplift, or RAG answer quality.
- These public-data artifacts are benchmark-only and are not linked to live
  shops. No LightFM model or reinforcement-learning policy was trained or
  activated; live LightFM still requires shop-scoped, consented exposure and
  feedback data that passes its quality gate.
