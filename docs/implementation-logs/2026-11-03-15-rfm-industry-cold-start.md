# RFM industry prior for new shops

Date: 2026-11-03

## Request

Let new shops benefit from the RFM segment model without waiting for the
shop-local threshold of 20 consented purchasing customers.

## Changes

- Built a privacy-safe industry prior from audited public RFM profiles using
  balanced per-source sampling and `MiniBatchKMeans` over normalized ordinal
  RFM features. The serving artifact stores centroids, segment labels, dataset
  provenance, and a checksum; it contains no customer IDs or transaction rows.
- Added serving selection in `recommendation_service.py`: use a successfully
  trained shop-local segmenter when present; otherwise use the configured
  industry prior for a customer with purchase history and valid personalization
  consent. Customers without completed purchases stay in `no_purchase`.
- Stored the effective model version, source/backing industry, confidence, and
  consented-peer count in recommendation request and displayed-item feature
  snapshots for later analysis.
- Monetary scoring is normalized using the median lifetime spend of the shop's
  currently consented buyers once at least five such buyers exist. Before that,
  monetary is neutral and R/F still provide the prior assignment.
- Kept the existing shop-local MiniBatchKMeans threshold at 20 consented buyers.
  The industry prior is a cold-start initializer, not a substitute for learning
  the shop's own behavior.
- Added a shop setting/API for selecting retail reference data (`general_retail`,
  `fashion`, `grocery`, `ecommerce`). Services, B2B, and mixed shops use the
  cross-industry aggregate because no matching public transaction data was
  available. The UI now limits choices to the selected shop type.
- Added read-only Docker mounts for the backend and worker, and documented the
  model flow and limitations.

## Artifact provenance

The prior includes 52,716 balanced profiles for the cross-industry model,
30,216 for general retail/ecommerce, 20,000 for fashion, and 2,500 for grocery.
Source datasets: Dunnhumby, H&M, Olist, Online Retail, and Online Retail II.
Artifact SHA-256:

`124eac72fbab475c759019f2591a9dfccddd36f6e0c70bcf75de9b63d553700a`

## Verification and limits

- Python syntax compilation succeeded for the changed RFM/API/script modules.
- `git diff --check` completed without whitespace errors.
- The backend loaded the checked-in artifact with checksum validation and
  returned a sample fashion-prior assignment (`low` confidence with one local
  consented buyer).
- The frontend production build succeeded. Vite reported its existing large
  main-chunk warning (about 1.15 MB before gzip).
- No test suite, database migration, Docker rebuild, or live recommendation
  request was run in this change. Restart/recreate the backend and worker after
  pulling these changes so the new artifact mount and serving code are loaded.
- The model provides a segment prior after a consented customer has purchase
  data. It cannot infer RFM or product affinity for a shop/customer with no
  transaction history, and it does not mean the shop has been trained on its
  own behavior.
