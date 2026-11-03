# RFM full dataset cleaning and training audit

## Request

Inventory all datasets under `D:\CRM_Industry_Datasets`, show row-level cleaning decisions, run logs and result logs, train eligible datasets, and identify which sources can inform the multi-shop RFM implementation.

## Run

- Started: 2026-11-03 07:23:00 UTC
- Finished: 2026-11-03 07:26:33 UTC
- Duration: 213.232 seconds
- Audit folder: `D:\CRM_Industry_Datasets\training_audit_runs\run_20261103_142300`
- Human-readable report: `D:\CRM_Industry_Datasets\training_audit_runs\run_20261103_142300\REPORT.md`
- Run command: `python scripts\run_rfm_dataset_suite.py --data-root D:\CRM_Industry_Datasets`
- Result: all six training jobs completed successfully.

## Dataset inventory

The audit saw 12 dataset folders: five full-RFM candidates, one RF-only candidate, five unsuitable for RFM, and one empty folder. Top-level archives whose extracted folders already existed were recorded and not processed twice. No Telco folder was present.

The approximately 32.19 GiB `archive` folder is H&M data: 105,100 JPG product images and four CSV files. RFM used the 3.25 GiB `transactions_train.csv`; it streamed all 31,788,324 rows and did not use the images.

## Training results

| Source | Rows seen | Rows accepted | Customers | Baskets | Monetary | RFM silhouette | Next-basket NDCG@5 |
|---|---:|---:|---:|---:|---|---:|---:|
| Dunnhumby | 2,595,732 | 2,576,815 | 2,500 | 275,539 | Yes | 0.267922 | 0.901660 |
| Olist | 112,650 item rows | 110,197 | 93,358 | 96,478 | Yes, merchandise price only | 0.387193 | 0.440386 |
| Online Retail | 541,909 | 397,884 | 4,338 | 18,532 | Yes | 0.329651 | 0.934171 |
| Online Retail II | 1,067,371 | 805,549 | 5,878 | 36,969 | Yes | 0.316225 | 0.927406 |
| Retailrocket | 2,756,101 events | 22,457 transaction events | 11,719 | 17,672 | No | 0.368611 | 0.752336* |
| H&M full transactions | 31,788,324 | 31,788,324 | 1,362,281 | 9,080,179 customer-date baskets | Yes | 0.422889 | Not run |

`*` Retailrocket's NDCG is a behavior/next-item experiment, not an RFM result. Its dataset has no monetary value, so it must not be treated as complete RFM.

## Cleaning ledger

- **Dunnhumby:** excluded 14,466 nonpositive-quantity rows and 4,451 nonpositive-sales rows. Duplicate customer/basket/product lines are aggregated.
- **Olist:** retained delivered-order item rows and mapped each customer to its customer ID. Excluded 2,963 non-delivered orders and 2,453 item rows not belonging to a delivered order. Aggregated 10,001 repeated customer/order/product rows. Monetary is item `price`; freight is excluded.
- **Online Retail:** excluded 9,288 cancellation invoices, 134,697 rows without customer ID, and 40 nonpositive-amount rows; aggregated 10,043 repeated invoice/product rows.
- **Online Retail II:** excluded 19,494 cancellation invoices, 242,257 rows without customer ID, and 71 invalid date/numeric rows; aggregated 36,684 repeated invoice/product rows.
- **Retailrocket:** retained transaction events only; excluded 2,733,644 view/add-to-cart events and aggregated 134 repeated transaction-item rows. Monetary is unavailable.
- **H&M:** zero rows failed customer/date/price validity checks; frequency is distinct purchase dates per customer, and Monetary is the sum of positive source price values.

Each source run stores `data_cleaning_log.json`, `training_report.json`, `run.log`, `rfm_profiles.csv`, and a fitted `rfm_segmenter.joblib`. Next-basket candidates also store `next_basket_ranker.joblib`. H&M's memory-bounded full run intentionally trained RFM only.

## Screened out

- Bank Marketing: contact/campaign outcomes, not customer purchase transactions.
- Expedia: search/booking records without the required customer-level spend and repeated transaction history.
- Online Shoppers Purchasing Intention: session intent and no stable customer purchase history.
- Wholesale Customers: annual spend by category without transaction event dates/frequency.
- Yelp: reviews/tips/check-ins, not purchases with monetary amount.
- `DwnlData`: empty.

These were inventoried and schema-screened; they were not transformed into fake RFM profiles.

## Recommendation for RFM

Keep the five complete transaction datasets as **separate offline benchmarks**. For the production multi-shop CRM, reuse the common cleaning and feature approach, but fit/refresh profiles and cluster boundaries separately using each shop's consented orders, currency, catalog and business cycle. Do not concatenate public customer IDs, share monetary scales, or load public segmenter weights into live shops.

Online Retail and Online Retail II produced high next-basket NDCG in their own time-split experiments; Dunnhumby also scored strongly. These values are not comparable across different catalogs/splits, and do not prove improved CRM conversion. H&M is the best full-scale test of the memory-bounded RFM pipeline. Olist is useful as a marketplace schema test. Retailrocket can inform RF behavior, but not Monetary.

No public set here contains RAG impressions, query context, displayed candidates and feedback propensities. These runs do not train RAG retrieval weights or LinUCB. They also do not justify turning on any public model artifact in a tenant.

## Verification and repository changes

- `training_results.csv` reports all six jobs as `completed`.
- Verified each run wrote cleaning, report and model/profile artifacts; H&M produced 1,362,281 customer profile rows per its training report.
- Python syntax compilation passed for `run_rfm_dataset_suite.py`, `train_industry_recommender.py` and `train_hm_full_rfm.py`.
- `git diff --check` returned no whitespace errors; it only printed the existing LF-to-CRLF working-copy notices.
- No database migration, production serving change, test suite, commit or push was performed for this training request.

