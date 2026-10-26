# CLO4 — Kiểm thử và triển khai hệ thống

Ngày kiểm tra: 25/10/2026. Mã Git gốc: `7510bbd`; working tree có nhiều thay đổi chưa commit, nên để lặp lại phép đo cần dùng chính working tree này. Môi trường: Docker Compose cục bộ, PostgreSQL 16/pgvector, Redis, backend, worker và frontend. Dữ liệu đánh giá là bộ mẫu trong repo; không dùng dữ liệu khách hàng thật.

## Phương pháp và phạm vi

Áp dụng **ma trận truy vết yêu cầu → ca kiểm thử → bằng chứng**, kết hợp kiểm thử hồi quy theo rủi ro và smoke test sau triển khai. Định tuyến được đo trên bộ nhãn 100 câu và bộ thương mại 32 câu; RAG được đo khả năng tìm đúng nguồn (Recall@5), không đánh đồng với chất lượng câu trả lời của LLM. Kiểm thử kênh dùng mock/fixture, không gửi tin thật tới Facebook, Instagram, Zalo hoặc TikTok.

| Tiêu chí | Phép kiểm | Kết quả | Đánh giá |
| --- | --- | --- | --- |
| Chức năng backend | 6 bộ test hợp đồng kênh, giao tin, phát lại sự kiện và độ ổn định RAG | 34/34 đạt | Đạt trong phạm vi test |
| Chức năng frontend | `npm test` | 314/317 đạt; 3 lỗi | Chưa đạt hoàn toàn |
| Build frontend | `npm run build` | Thành công; bundle JS 1.112 MB có cảnh báo kích thước | Đạt build, cần tối ưu tải trang |
| Ổn định nhận/gửi | Retry, idempotency, recovery và delivery | 11/11 đạt khi chạy với cấu hình pytest đầy đủ | Đạt theo fixture; chưa đo soak/load |
| Đồng bộ nền tảng | Webhook, outbound, bridge và nhập lịch sử cho Meta/Instagram, Zalo, TikTok, Telegram | 111 đạt, 3 bỏ qua | Đạt fixture; chưa nghiệm thu trực tiếp |
| Định tuyến chatbot | 100 câu có nhãn; Accuracy, Macro F1 | 1,000; 1,000 | Đạt bộ mẫu ngoại tuyến |
| NLU thương mại | 32 câu có nhãn; Accuracy, Macro F1 | 1,000; 1,000 | Đạt bộ mẫu ngoại tuyến |
| Truy xuất RAG | 32 ca có nguồn tài liệu đã biết; Recall@5 | 1,000 | Đạt lexical fallback trên tài liệu demo |
| CRM/RAG có cấu trúc | 13 ca SQLite tổng hợp | Action accuracy 1,000; retrieval recall 1,000; contract pass 1,000 | Đạt fixture nhỏ |
| Triển khai cục bộ | Compose config, container health, backend `/health`, đối chiếu revision | 5/5 container healthy; HTTP 200; backend/worker/source cùng revision `1983ebf07d2fe091` | Đạt smoke test cục bộ |

### Phép đo mô hình

- **Accuracy** = số nhãn dự đoán đúng / tổng số mẫu. **Macro F1** = trung bình F1 của từng lớp, tránh để lớp nhiều mẫu che lớp ít mẫu. Xem [chỉ số và từng lớp](clo4-intent-metrics.json).
- **Recall@5** = tỷ lệ ca có tài liệu nguồn mong đợi xuất hiện trong 5 kết quả đầu. Có 40 ca RAG mẫu, nhưng chỉ 32 ca có nguồn tài liệu rõ; 8 ca nguồn là dữ liệu CRM có cấu trúc hoặc ngoài bộ demo nên không đưa vào mẫu số. Xem [kết quả truy xuất](clo4-rag-retrieval.json).
- **RMSE không áp dụng** cho nhãn ý định/phân loại. Chưa có bộ nhãn số của bài toán dự đoán giá, nhu cầu hoặc doanh thu; tính RMSE trên mã nhãn sẽ không có ý nghĩa. Nếu sau này triển khai dự báo số, cần bộ ground truth theo thời gian và split train/test trước khi báo RMSE.
- Kết quả [CRM/RAG tổng hợp](clo4-crm-rag.json) dùng SQLite, không gọi LLM, embedding hoặc API bên ngoài. Các tỷ lệ 1,000 ở đây không chứng minh bot trả lời đúng 100% trong hội thoại thực tế.
- Độ trễ p95 của **13 ca xử lý tổng hợp trong máy** là 61,51 ms; số này không bao gồm thời gian LLM, webhook hay chuyển phát nền tảng.

### Đồng bộ kênh

Chạy 9 nhóm test `test_instagram_webhook`, `test_instagram_outbound`, `test_zalo_webhook`, `test_zalo_outbound`, `test_tiktok_webhook`, `test_telegram_outbound`, `test_meta_business_suite_bridge`, `test_history_import`, `test_connector_health_state`: **111 passed, 3 skipped** trong 92,15 giây. Những ca này kiểm tra hợp đồng request/response, xác thực, trạng thái bridge, đồng bộ lịch sử và chống trùng bằng mock/fixture. Facebook được kiểm qua Meta Business Suite bridge và bộ test hợp đồng kênh, nhưng chưa đo luồng thực từ tài khoản khách tới Page rồi quay lại. Shopee chưa có bộ test tự động tương ứng trong lượt này. Không suy ra tỷ lệ đồng bộ thực tế của từng nền tảng từ tổng 111 ca.

### Phát hiện và sửa trong lượt này

1. Bộ 100 câu ban đầu sai 2 ca: câu hỏi SKU cụ thể bị hiểu thành hỏi toàn danh mục; câu hỏi shop có bán một mã hàng bị chuyển sang tìm tài liệu. Sửa thứ tự nhận diện **mã/tên hàng cụ thể** trong router dùng chung, thêm assertion hồi quy. Sau sửa: 100/100; bộ thương mại độc lập 32/32. Test hồi quy đích: 1/1 đạt.
2. Backend trước smoke test có `loaded_revision` khác `source_revision`: worker và backend có thể trả theo mã cũ. Đã restart **backend và worker cùng lúc**; script `scripts/check-runtime-revisions.ps1` xác nhận cả ba revision trùng `1983ebf07d2fe091`.
3. Bộ test kênh khi chạy với `--noconftest` lỗi `SQLite: no such table: channels` vì thiếu fixture khởi tạo bảng. Đây là lỗi cách chạy test, không phải bằng chứng nền tảng thật mất đồng bộ. Chạy lại test độ ổn định với conftest: 11/11 đạt.
4. Frontend còn 3 test đỏ: hai test kiểm tra cấu trúc UI cũ (`admin-navigation`, `crm-shell`), và một lỗi thực về 21 chuỗi tiếng Việt chưa có bản dịch tiếng Anh trong UI thanh toán/cấu hình. Không được coi là đã nghiệm thu giao diện đa ngôn ngữ.

### Lệnh tái lập

Chạy trong container backend đã cài đủ dependency và có bộ dữ liệu demo dưới `/docs`, `/knowledge_base`:

```powershell
docker exec -w /app crm_chatbot_backend python /scripts/evaluate_clo4.py --output /docs/qa-runs/2026-10-25/clo4-intent-metrics.json
docker exec -w /app crm_chatbot_backend python /scripts/evaluate_rag_quality.py
docker exec -w /app crm_chatbot_backend python /scripts/evaluate_crm_rag.py
docker exec -e 'ALLOWED_HOSTS=*' -w /app crm_chatbot_backend python -m pytest -q tests/test_channel_contracts.py tests/test_channel_reliability.py tests/test_channel_delivery.py tests/test_channel_event_replay_api.py tests/test_rag_stability_acceptance.py tests/test_rag_evaluation_set.py --disable-warnings
docker exec -e 'ALLOWED_HOSTS=*' -w /app crm_chatbot_backend python -m pytest -q tests/test_instagram_webhook.py tests/test_instagram_outbound.py tests/test_zalo_webhook.py tests/test_zalo_outbound.py tests/test_tiktok_webhook.py tests/test_telegram_outbound.py tests/test_meta_business_suite_bridge.py tests/test_history_import.py tests/test_connector_health_state.py --disable-warnings
docker exec crm_chatbot_frontend npm test
docker exec crm_chatbot_frontend npm run build
docker compose -p smart-merchant-hub-runtime -f docker-compose.yml config --quiet
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check-runtime-revisions.ps1
```

Các JSON cạnh báo cáo là đầu ra máy đọc được của phép đo. `evaluate_clo4.py` có self-check cho công thức Accuracy. Các file nguồn bộ mẫu nằm tại `docs/chatbot-evaluation-set.jsonl`, `docs/commerce-nlu-evaluation-set.json`, `docs/crm-rag-evaluation-set.jsonl`.

## Giới hạn nghiệm thu và việc cần làm trước AWS

Đây là **kiểm thử và triển khai cục bộ**, chưa phải triển khai AWS. Chưa có phép đo end-to-end trên tin thật của mọi nền tảng, kiểm thử tải/soak nhiều giờ, hay bộ chấm chất lượng câu trả lời LLM có người duyệt. Cần xử lý 3 test frontend đỏ, chạy thử hai chiều với từng tài khoản kênh trong môi trường staging, đo tỷ lệ nhận/gửi/trùng tin và độ trễ p95, rồi mới kết luận hệ thống sẵn sàng cho doanh nghiệp. Trước khi chuyển PostgreSQL lên AWS cần thêm backup/restore drill, kiểm thử migration trên bản sao DB, cấu hình secrets và kết nối TLS.
