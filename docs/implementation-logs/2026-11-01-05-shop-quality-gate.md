# 05 — Đánh giá theo thời gian, quality gate và rollback riêng từng shop

**Trạng thái:** Đã nối code train/serving; chưa chạy trên DB thật.

## Đã làm

- Trainer lọc log theo consent hiện hành, chạy riêng từng tenant, chia holdout 80/20 theo thời gian và ghi số shop/request/khách consent/event cùng cửa sổ train/holdout.
- So sánh cùng candidate snapshot giữa baseline và baseline + reranker: NDCG@3, Precision@3, tỷ lệ mua/bỏ qua, propensity và vi phạm top 3.
- Quality gate từ chối model nếu NDCG giảm, thiếu consent/sample, thiếu validation của bất kỳ offer top 3 nào, hoặc tăng vi phạm shop, trạng thái, tồn kho, SKU/loại đối tượng/thuộc tính bắt buộc.
- Lưu trạng thái model, gate, phiên bản, training run và cửa sổ theo từng shop trong `recommendation_shop_model_states`. Serving chỉ nạp artifact đúng tenant, đúng run/version và `gate_status=passed`; thiếu bảng hoặc trạng thái thì dùng baseline.
- Candidate đủ dữ liệu nhưng trượt gate sẽ tắt model cho shop đó và quay về baseline. Một lượt train thiếu mẫu giữ model đã active trước đó; attempt vẫn được ghi.
- Rút consent/opt-out xóa artifact pairwise/LightFM của shop, tắt trạng thái model và xóa cache factor LightFM; cần train lại từ nhóm còn consent trước khi bật lại.

## Tệp

- `backend/scripts/train_live_recommendation_reranker.py`
- `backend/app/services/recommendation_service.py`
- `backend/app/services/privacy_service.py`
- `backend/app/models/recommendation_quality_gate.py`
- `backend/alembic_tenant/versions/20261101_0015_recommendation_catalog.py`
- `docs/live-recommendation-learning.md`

## Giới hạn và xác minh

- Snapshot cũ không có `quality_validation` đầy đủ sẽ bị gate từ chối an toàn; cần migration, đồng bộ catalog và impressions mới trước khi đánh giá đủ điều kiện.
- Đây là quality gate offline trên log đã hiển thị, không phải giám sát drift online hay A/B test. Chưa có rollback tự động vì drift sau khi model đã bật.
- Ghi chú trạng thái trước khi chạy migration, train và đánh giá trên local DB; kết quả runtime cập nhật bên dưới. Không commit/push.

## Runtime result (2026-11-01)

- Migration đã áp dụng; reranker được chạy riêng từng shop trên local Docker PostgreSQL với chia theo thời gian.
- 14/14 shop được ghi training attempt; tất cả `insufficient_data`. Shop 4 có 11 exposure groups, 1 khách consented, 0 positive holdout requests; các shop còn lại chưa đủ hai exposure groups.
- Baseline NDCG/Precision trên holdout không tính được khi không có positive holdout. Quality gate không đạt; không model nào được kích hoạt.
- JSON đầy đủ: `2026-11-01-reranker-training-evaluation.json`.

## Kiểm tra cuối

- Full backend suite: **1,625 passed, 6 skipped, 37 subtests passed**; log `2026-11-01-backend-tests-postgres-final.log`.
- Huấn luyện/đánh giá đã chạy trên 14 shop nhưng mọi shop đều `insufficient_data`. Shop 4 có 11 exposure requests, 1 khách consent, 0 positive holdout; các shop khác không đủ hai exposure requests.
- Không có baseline-vs-reranker metric đủ điều kiện để công bố; chưa bật model và chưa chạy production/A-B test.
