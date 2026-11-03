# Huấn luyện gợi ý từ bộ dữ liệu ngành

Chạy lệnh từ thư mục gốc repository. Dữ liệu nguồn nằm ngoài Git ở `D:\CRM_Industry_Datasets`.

```powershell
python scripts\train_industry_recommender.py --source dunnhumby --max-events 0
python scripts\train_industry_recommender.py --source hm --max-events 500000
python scripts\train_industry_recommender.py --source olist --max-events 0
python scripts\train_industry_recommender.py --source retailrocket --max-events 0
python scripts\train_industry_recommender.py --source online_retail --max-events 0
python scripts\train_industry_recommender.py --source online_retail_ii --max-events 0
python scripts\train_hm_full_rfm.py
```

The two UCI Online Retail workbooks require `python -m pip install openpyxl`.
Their adapters exclude missing customer IDs, cancelled invoices, and
non-positive quantity/price rows before building invoice-level RFM.

For the 3.25 GB H&M transaction file, `train_hm_full_rfm.py` streams the entire
file and trains RFM clusters without building all baskets in memory. The 30+ GB
H&M archive size includes product images; they are not used for transaction RFM.
This full-data job trains the RFM segmenter only; next-basket ranking remains a
separate offline experiment.

To inventory every dataset folder, classify RFM eligibility, clean and train
all supported sources, and produce a single reproducible audit run:

```powershell
python scripts\run_rfm_dataset_suite.py --data-root D:\CRM_Industry_Datasets
```

The suite writes a timestamped `training_audit_runs/run_*` directory containing
inventory, archive de-duplication decisions, schema evidence, source eligibility,
per-source stdout logs, cleaning logs, model artifacts, and a combined result
CSV/JSON. Raw public-data customer identifiers and model artifacts remain
separate benchmarks; only the privacy-safe aggregate cold-start centroids are
activated in tenant serving (see below).

The full audit completed on 2026-11-03 at
`D:\CRM_Industry_Datasets\training_audit_runs\run_20261103_142300`.
Its human-readable `REPORT.md`, per-source cleaning logs, benchmark metrics and
dataset eligibility decisions are recorded there; the implementation log is
`docs/implementation-logs/2026-11-03-13-rfm-cleaning-and-full-dataset-suite.md`.

For live CRM training, use the shop-scoped segment trainer. It fits
`log1p + StandardScaler + MiniBatchKMeans` separately from each active shop's
own completed orders, and only includes customers with personalization
consent. Public D: drive model weights are not loaded into customer profiles.

```powershell
docker compose exec -T backend python /app/root-scripts/train_shop_rfm_segments.py --all-shops
```

The fitted cluster ID and model version are stored with that shop's customer
RFM profile and training-run record. Human-readable RFM segments remain
interpretable rules; the learned cluster is an additional per-shop feature and
does not override consent or replace the shop's transaction data.

## Cold-start model for new shops

New shops no longer have to wait for 20 consented buyers before the RFM model
can influence recommendation ranking. The checked-in, privacy-safe prior at
`backend/artifacts/industry_rfm/prior_model.json` contains only normalized RFM
centroids, cutoffs, source/run provenance, and a checksum manifest. It contains
no public customer IDs or transaction-level rows.

Build or refresh it from the audited public profile exports with:

```powershell
python backend\scripts\build_industry_rfm_prior.py `
  --models-root D:\CRM_Industry_Datasets\training_audit_runs\run_20261103_142300\models
```

The RFM industry reference is configurable under **Cài đặt shop → Loại hình
kinh doanh & tính năng**. Available references are general retail, fashion
(H&M), grocery (Dunnhumby), and ecommerce (Olist + the two UCI Online Retail
sets). Services, B2B, and mixed shops use the cross-industry prior because the
audited folder did not contain appropriate service/B2B transaction data; the
setting does not claim those centroids are trained specifically for those
verticals.

When a consented customer has at least one completed purchase, serving assigns
the closest prior cluster immediately. Monetary is normalized against the
median spend of currently consented buyers in that shop; until five such peers
exist, Monetary stays neutral and the prior uses Recency and Frequency. A
customer with no purchase remains in the explicit `no_purchase` group. Existing
personalization consent and opt-out checks still gate customer-level features.

The prior is a cold-start initializer, not evidence that a new shop has learned
its own behavior. After at least 20 consented buyers, the existing tenant-local
trainer can fit the shop's own MiniBatchKMeans model. Its cluster assignment is
then used for that shop; public identifiers and another shop's customer data
are never copied into the tenant.

The first all-shop Docker run was executed on 2026-11-03. All 14 jobs completed,
but **zero shops had 20 consented purchasing customers**, so no per-shop model
was fitted. See `shop_rfm_training_report.json` and `shop_rfm_readiness.jsonl`
in the audit run folder. Consented buyers now use the aggregate industry prior
until a shop-local model is successfully trained; customers with no completed
purchase remain in the explicit `no_purchase` segment.

Mỗi lượt tạo thư mục riêng dưới `D:\CRM_Industry_Datasets\trained_models\<source>\run_*` gồm:

- `rfm_profiles.csv`: Recency, Frequency, Monetary và mã cụm phân tích.
- `rfm_segmenter.joblib`: `StandardScaler + MiniBatchKMeans`.
- `next_basket_ranker.joblib`: `StandardScaler + LogisticRegression` để xếp hạng giỏ mua tiếp theo so với sản phẩm âm được lấy mẫu.
- `training_report.json`: số dòng đọc, giới hạn lấy mẫu, Precision@5, Recall@5, NDCG@5 và giới hạn của lượt train.

Mặc định đọc tối đa 500.000 dòng mua để tránh dùng quá nhiều RAM; `--max-events 0` đọc toàn bộ. Nên chạy Dunnhumby và Olist đầy đủ trước; H&M có thể chạy tăng dần bằng cách tăng giới hạn.

## Giới hạn và cách dùng

- Giữ mỗi ngành và bộ nguồn riêng: ID khách, ID sản phẩm, tiền tệ và cách ghi nhận giao dịch không dùng chung được.
- Ranker dùng nhãn proxy “nằm trong giỏ kế tiếp” với negative sampling và chia dữ liệu theo thời gian. Các metric là benchmark next-basket, không phải conversion uplift hay chất lượng câu trả lời RAG.
- Retailrocket không có doanh thu nên Monetary không khả dụng; báo cáo đánh dấu điều này.
- UCI Online Retail and Online Retail II are valid transaction sources for RFM;
  customer IDs, invoice dates, quantities, and prices are available. Exclude
  cancellation invoices and non-positive quantity/price records.
- Expedia hotel searches, bank marketing, online shopping intention, wholesale
  annual summaries, and Yelp reviews in the audited D: drive do not provide the
  required combination of customer-level purchase time, frequency, and monetary
  value. No Telco dataset folder was found in that audit. Do not label those
  outputs as RFM; they need different feature definitions.
- Các bộ công khai không chứa truy vấn khách và danh sách sản phẩm đã được RAG hiển thị. Vì vậy không thể học trọng số Gemini/BM25/RRF/PPR hoặc huấn luyện LinUCB đúng nghĩa từ chúng.
- Raw benchmark artifacts remain offline and are not loaded into a tenant. Only the privacy-safe aggregate prior described above is used for cold-start RFM; customer profiles and product candidates still come from each tenant's own CRM data.
- Muốn huấn luyện reranker RAG có giám sát, cần log cho từng lần hiển thị: query, RFM snapshot, candidate product IDs, điểm BM25/vector/RRF/PPR, vị trí hiển thị và phản hồi click/cart/purchase/skip.
- Chỉ huấn luyện LinUCB sau khi có các lượt hiển thị, hành động được chọn, xác suất chọn và kết quả thật. Không xem đơn hàng tĩnh là log khám phá của bandit.
