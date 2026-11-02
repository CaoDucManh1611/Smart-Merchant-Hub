# 07 — LightFM theo RFM, danh sách khách hàng và danh tính audit

**Trạng thái:** Đã nối vào code; cú pháp Python và production build frontend đạt. Chưa chạy bộ test, migration, huấn luyện hay đánh giá dữ liệu thật trong lượt này.

## LightFM và RFM

- Đổi phiên bản artifact sang `lightfm_warp_rfm_v2`; artifact cũ không có RFM features sẽ không được scorer mới nhận.
- Huấn luyện user features gồm identity HMAC theo shop và bucket R/F/M quintile. Ranh giới bucket được tính từ snapshot hợp lệ của tập train theo thời gian trong từng shop.
- Trainer chỉ lấy interaction của khách đã qua bộ lọc consent hiện hành; yêu cầu tối thiểu 80% khách có tương tác dương trong train có snapshot RFM đầy đủ.
- Serving đưa snapshot RFM hiện hành và trạng thái consent vào scorer. Thiếu consent, snapshot, item factor hoặc feature version thì model trả `None`, giữ baseline.
- Khi rút consent, luồng invalidation cũng xóa artifact LightFM phiên bản cũ `lightfm_warp_v1`, ngoài phiên bản hiện tại.
- Temporal holdout, blend baseline, đo NDCG/Precision và quality gate vi phạm cứng vẫn là điều kiện trước khi artifact được bật.

## Trang quản lý khách hàng cho shop

- Thêm tab `Danh sách khách hàng`, giữ trạng thái tab khi chuyển trang trong workspace.
- Trang dùng API tenant-scoped hiện có, hỗ trợ tìm trực tiếp khi gõ theo tên/email/điện thoại/tài khoản kênh (debounce 250 ms), lọc nền tảng, tải thêm danh sách và mở hồ sơ 360 gồm liên hệ, định danh đa kênh, nhãn và hội thoại gần đây.
- Thêm điều kiện `q` và `channel` cho endpoint danh sách; truy vấn định danh phụ được giới hạn cùng `business_id`.

## Nhật ký thao tác

- API audit nối `user_id` với tài khoản cùng shop và trả `actor_name`, `actor_email`, `actor_role`.
- Trang Cài đặt hiển thị tên, email và vai trò của nhân viên thực hiện; nếu không còn tài khoản tương ứng sẽ hiện ID nhân viên, còn thao tác hệ thống được ghi rõ là hệ thống.
- Giữ quyền xem audit log hiện hành chỉ cho chủ shop/quản trị viên.

## Kiểm tra và giới hạn

- Chưa chạy test theo yêu cầu mặc định của phiên làm việc; chưa cài LightFM, chưa chạy trainer trên dữ liệu thật, chưa bật model và không chạy migration.
- `python -m py_compile` cho API/schema/scorer/trainer: đạt. `npm run build`: đạt; tab khách hàng được tách chunk riêng. Vite còn cảnh báo chunk chính hiện tại vượt 500 kB.
- `git diff --check`: không phát hiện lỗi whitespace; Git báo khác biệt line ending LF/CRLF cho `backend/app/schemas/auth.py` trên Windows.
- Không commit hoặc push.
