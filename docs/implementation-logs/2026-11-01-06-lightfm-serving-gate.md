# 06 — LightFM reranker tùy chọn và gate trước khi phục vụ

**Trạng thái:** Đã nối trainer/scorer vào serving; chưa huấn luyện hoặc bật model.

## Đã làm

- Thêm `lightfm_warp_v1` vào trainer hiện có, dùng implicit positive click/cart/purchase từ những sản phẩm thực sự được impression, chỉ lấy khách còn consent và chia train/holdout theo thời gian trong từng shop.
- Mã hóa customer identity bằng HMAC với `CHANNEL_ENCRYPTION_KEY`; raw customer ID không được ghi vào factor artifact. Khách chưa consent, khách mới và sản phẩm chưa có factor giữ baseline.
- Lưu factor/bias ở dạng float16 nén trong JSON của training run; serving giải nén theo demand và trộn điểm LightFM chuẩn hóa với thứ hạng baseline hiện có. Không thay retrieval, hard filter, tồn kho hoặc RFM trong baseline.
- Serving chỉ chạy LightFM khi model state của đúng shop vượt quality gate. Gate yêu cầu tối thiểu 10 khách consent, 30 positive event, 20 request train, 5 positive holdout request, ít nhất 80% positive holdout request có đủ score LightFM, NDCG@3 không giảm và vi phạm cứng không tăng.
- Thêm dependency tùy chọn `backend/requirements-lightfm.txt`; backend serving không cần import/cài LightFM, chỉ môi trường huấn luyện cần package này.
- Consent bị rút sẽ xóa artifact học được, vô hiệu hóa gate và xóa factor cache trong tiến trình; sau đó phải train lại.

## Tệp

- `backend/app/services/recommendation_learning.py`
- `backend/app/services/recommendation_service.py`
- `backend/app/services/recommendation_interaction_service.py`
- `backend/scripts/train_live_recommendation_reranker.py`
- `backend/requirements-lightfm.txt`
- `docs/live-recommendation-learning.md`

## Giới hạn và xác minh

- LightFM hiện phục vụ đối tượng `product` vì API serving/candidate snapshot/feedback hiện tại là product-centric. Catalog service/rental đã có projection nhưng chưa có luồng impression/conversion và availability chung đủ để huấn luyện/serve LightFM cho hai loại đó; model không được bật cho chúng.
- Đây là ghi chú trạng thái trước lượt chạy trainer/migration/test ghi bên dưới. Chưa có kết quả chất lượng thực để kết luận LightFM tốt hơn pairwise hoặc baseline.
- LightFM cung cấp WARP và implicit-feedback training theo hướng dẫn repo chính thức: [lyst/lightfm](https://github.com/lyst/lightfm).
- Không commit/push.

## Runtime result (2026-11-01)

- Đã chạy pipeline LightFM theo từng shop; 14/14 attempt được lưu, tất cả `insufficient_data` trước bước fit vì thiếu khách đồng ý và positive holdout.
- Gói tùy chọn LightFM chưa cài trong môi trường; dữ liệu đã bị quality gate chặn trước khi cần import dependency nên không fit model giả tạo.
- Không kích hoạt model; JSON đầy đủ: `2026-11-01-lightfm-training-evaluation.json`.

## Kiểm tra cuối

- Full backend suite: **1,625 passed, 6 skipped, 37 subtests passed**; log `2026-11-01-backend-tests-postgres-final.log`.
- 14 shop đều bị chặn ở quality gate vì thiếu dữ liệu consent/positive holdout; LightFM chưa fit, chưa bật và dependency tùy chọn chưa cài.
- Chưa có chỉ số so sánh LightFM với baseline; cần impressions và tương tác đủ mẫu theo shop trước khi đánh giá.
