# Shop-scoped RFM model integration and live training

## Request

Train the downloaded industry datasets and bring the useful RFM method into the CRM, so shop owners do not need to run training themselves.

## Implementation

- Added a shop-scoped live trainer using `log1p + StandardScaler + MiniBatchKMeans` with up to four clusters and a fixed random seed.
- Live fit uses that shop's completed-order RFM features and only customers with the latest `personalization` consent granted while the shop personalization setting is enabled.
- Cluster ID, model version, cluster sizes, silhouette sample score and model centers/scaler are recorded in the shop-local recommendation profile/training-run record. Rule-based RFM labels remain the serving fallback and stay interpretable.
- Removed use of public demo clustering artifacts from the live training path. Public datasets remain isolated benchmarks; their customer IDs, money scales and fitted weights are not pushed into tenant schemas.
- Updated manual, customer-classification and weekly-job training metadata to use `shop_scoped_rfm_minibatch_kmeans` / `shop_rfm_minibatch_kmeans_v1`.
- Added `scripts/train_shop_rfm_segments.py` to execute shop-scoped RFM fitting for one active tenant or all active feature-enabled shops.

## Live run

- Docker backend and worker were restarted to load the code; backend health returned HTTP 200 and both containers became healthy.
- Ran `python /app/root-scripts/train_shop_rfm_segments.py --all-shops` inside the backend container.
- 14 active, feature-enabled shop schemas were processed; all 14 training-run operations completed without an execution error.
- **Zero customer cluster models were fitted or activated.** The database has 58 non-merged customers across these shops and one latest granted personalization consent, but that customer has no completed order. No shop meets the minimum of 20 consented buyers.
- Personalization setting was enabled for all 14 shops. Shops 1, 3 and 7 have customers but no granted consent; shop 4 has 28 customers, one granted consent and zero consented buyers; the other 10 shops have no customer records.
- RFM labels therefore remain on the rule-based fallback. The one consenting but non-buying shop-4 customer remains in the `no_purchase` segment; there is no model trained from that row.

## Logs and verification

- Public-data benchmark and full cleaning reports: `D:\CRM_Industry_Datasets\training_audit_runs\run_20261103_142300\REPORT.md` and `training_results.csv`.
- Live shop training JSONL: `D:\CRM_Industry_Datasets\training_audit_runs\run_20261103_142300\live_shop_rfm_training.jsonl`.
- Shop consent/order readiness: `D:\CRM_Industry_Datasets\training_audit_runs\run_20261103_142300\shop_rfm_readiness.jsonl`.
- Combined live run report: `D:\CRM_Industry_Datasets\training_audit_runs\run_20261103_142300\shop_rfm_training_report.json`.
- Python syntax compilation passed for the changed service, APIs, worker and training script. No pytest suite or migration was run.
- No commit or push was performed.

## Current limit and activation condition

The application now has the automatic, per-shop training path, but it cannot honestly show a learned cluster model until at least 20 customers in a shop both consent to personalization and have completed purchase history. Once that data exists, manual RFM classification, the weekly learning job, or the new script can fit the model. Public-data artifacts cannot substitute for missing consented tenant purchase history.

