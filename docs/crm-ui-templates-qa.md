# Kiểm tra giao diện CRM UI Templates

Ngày kiểm tra: 2026-10-04. Phạm vi thay đổi: frontend và tài liệu mẫu; không sửa backend hay schema trong phần việc này.

| Màn / luồng | Đã kiểm tra | Kết quả / giới hạn |
| --- | --- | --- |
| Trang gói dịch vụ công khai | Trình duyệt thực tại 375, 768, 1440 px; tiếng Việt/Anh; kiểm tra lỗi console và tràn ngang | Không có tràn ngang sau khi sửa lưới mobile; không có lỗi console trong các lần kiểm tra. |
| Popup xác nhận gửi yêu cầu | Kiểm tra mã nguồn và test tự động cho trạng thái thành công, focus, Esc/Tab, reduced motion | Đã xem trang gói tại 5173; chưa gửi yêu cầu thật để tránh tạo yêu cầu gói trả phí. |
| Danh mục sản phẩm / link sản phẩm | Kiểm tra trên tài khoản shop tại 5173: trường link hiện sau khi mở chỉnh sửa; URL `javascript:` bị chặn trước khi lưu. Test tự động URL, liên kết an toàn và hợp đồng import | Chưa ghi link hợp lệ vào bản ghi sản phẩm thật; chưa xác minh đường đọc/ghi API bằng E2E. |
| File mẫu sản phẩm / đơn bán | HTTP 200 cho hai file; kiểm tra nút tải mẫu sản phẩm/đơn bán trên giao diện; test tự động đối chiếu cột CSV | Chưa nhập dữ liệu thật. |
| Email OTP | Kiểm tra màn email tài khoản và SMTP riêng của shop trên tài khoản chủ shop tại 5173 | Không gửi OTP, không đổi email thật. |
| Kết nối Shopee/TikTok | Kiểm tra thẻ kênh và modal Shopee tại 5173: Shopee báo trực tuyến, TikTok báo ngoại tuyến, có hướng dẫn và nút thử kết nối lại | Không ghép nối/retry thật; chưa xác minh luồng truyền tin hai chiều. |
| Hồ sơ khách hàng 360, RFM/sở thích | Kiểm tra hộp thư và hồ sơ khách đã có tại 5173 | Khách được mở không có fact/RFM để kiểm tra nguồn và lý do gợi ý bằng dữ liệu thật. |

Kiểm tra kỹ thuật: `npm test` 210/210; `npm run build` thành công. Build còn cảnh báo bundle JavaScript lớn hơn 500 kB, không phải lỗi build.

Lưu ý triển khai: container frontend có bind mount đúng `C:\Users\DUC_STRONG\Smart-Merchant-Hub-full-stack-ready\frontend`, nhưng Vite trong container đã không tự nhận thay đổi file. Đã khởi động lại riêng `crm_chatbot_frontend` (không dừng DB/backend/worker) để cổng 5173 tải mã nguồn mới; kiểm tra lại thấy trường link sản phẩm và copy gói mới. Đã bật polling cho Vite trong Docker, tái tạo riêng container frontend và xác nhận container nhận `VITE_USE_POLLING=true`, đang healthy. Việc tự reload sau một lần sửa file tiếp theo chưa được quan sát trực tiếp.

Kết luận: các hạng mục giao diện đã kiểm tra đều hoạt động trong phạm vi không ghi dữ liệu. Chưa thể chốt nghiệm thu toàn bộ chức năng nghiệp vụ vì các bước gửi yêu cầu gói, OTP, lưu link hợp lệ, import và truyền tin qua connector chưa được chạy E2E trên bộ dữ liệu thử cách ly. Không nên gọi đây là chứng nhận sẵn sàng giao khách hàng.
