# Sửa chọn phiên bản và xem chi tiết Toner — 25/11/2026

Đã sửa và nạp vào backend/worker lúc 17:54 ngày 25/11/2026 (UTC+7).

## Nguyên nhân

Hai câu đầu trong hội thoại trả lời phù hợp. Hai câu chọn bản 100ml bị lỗi vì `catalog_dialogue_reply` vẫn gọi bộ phân loại từ xa trước khi giải quyết sản phẩm theo danh mục. Log worker ghi nhận `RateLimitError` (HTTP 429), rồi `ProviderCircuitOpen`; nhánh bắt lỗi trả đúng thông báo “Mình đang gặp trục trặc…” mà người dùng gửi.

## Thay đổi

Chỉ chỉnh mã ứng dụng trong `backend/app/services/catalog_dialogue.py`: bổ sung `_detail_catalog_scope` để nhận diện yêu cầu xem chi tiết có tên sản phẩm/nhóm rõ ràng và câu chọn dung tích trong ngữ cảnh gần nhất. Kết quả tiếp tục đi qua bộ lọc dung tích và bộ hiển thị thông tin danh mục sẵn có.

Nhánh mới chỉ áp dụng cho một nhóm đã xác định. Từ không rõ, yêu cầu nhiều nhóm và câu hỏi về cách dùng, mức độ phù hợp, chính sách, đơn hàng, gặp nhân viên tiếp tục theo luồng hiểu ý định hiện có. Phiên thu thập đang mở giữ nguyên quyền xử lý. Không bổ sung thông tin công dụng ngoài dữ liệu shop.

## Kiểm chứng

- Trước sửa: 7 ca lỗi, 12 ca qua; các ca lỗi tái hiện đúng thông báo trong hội thoại.
- Thêm 22 ca hồi quy trong `backend/tests/test_catalog_detail_variant_regression.py`, gồm ba ca bảo vệ yêu cầu có nhiều nhóm sau khi rà soát mã.
- Bộ kiểm tra cuối: **356 passed, 4 deselected**. Bốn ca `test_late_workflow_ref_collect_review_submit_with_bounded_prompt` lỗi về số lần gọi `record_quota_usage` đã được chạy lại trên bản mã chụp trước sửa trong thư mục cách ly: cả bốn vẫn lỗi tương tự. Không tuyên bố bộ kiểm tra chưa lọc đã qua toàn bộ.
- Phát lại đủ bốn câu qua `graph_reply` bằng bản sao 24 sản phẩm hiện tại của shop 8 trong SQLite kiểm thử. Chặn tất cả các lệnh gọi bộ phân loại, nhà cung cấp AI, gửi tin nhắn và công cụ giao dịch: số lần gọi đều bằng 0. Đơn hàng, lịch hẹn, ticket, phiên thu thập và tồn kho trong kiểm thử không thay đổi. Dữ liệu shop thật chỉ được đọc trong giao dịch `READ ONLY`.

## Kết quả hội thoại quan sát được

1. “shop đang bán gì”: liệt kê 12 nhóm đang kinh doanh.
2. “tôi muốn biết chi tiết Toner dưỡng ẩm”: đưa hai bản 100ml — 95.000 đồng và 200ml — 159.000 đồng.
3. “bản 100ml ấy”: trả Toner dưỡng ẩm 100ml — 95.000 đồng/sản phẩm, còn 31 sản phẩm tại thời điểm xuất dữ liệu, kèm mô tả có sẵn: bổ sung độ ẩm và cần đối chiếu nhãn trước khi tư vấn thực tế.
4. “chi tiết bản toner dưỡng ẩm 100ml ấy”: trả đúng bản 100ml với cùng dữ liệu; không báo lỗi xử lý.

## Trạng thái sau nạp bản sửa

Kiểm tra lúc **17:54:23 ngày 25/11/2026 (UTC+7)**: backend và worker đều `running healthy`; frontend HTTP 200; `/health` trả `ok`, `loaded_revision = source_revision = c6ce3fbcc2af8a17`.

Bằng chứng: `rag-chi-tiet-toner-after-20261125.json`, `rag-chi-tiet-toner-regressions-20261125.xml`, `rag-chi-tiet-toner-before-20261125.xml`, `rag-chi-tiet-toner-baseline-20261125.xml`, `rag-chi-tiet-toner-runtime-20261125.json` trong thư mục `reports/`.
