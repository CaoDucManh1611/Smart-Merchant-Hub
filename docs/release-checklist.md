# Smart Merchant Hub — checklist trước khi phát hành

Checklist này dùng cho bản demo/production tuần tới. Không dán secret thật vào
repo, issue hoặc terminal transcript.

## Tính năng cần nghiệm thu

- [ ] Customer 360 hiển thị đúng tên; email và số điện thoại được che một phần.
- [ ] Unified Timeline phân biệt Khách hàng, Chatbot, Nhân viên và Hệ thống.
- [ ] Bot nhớ sản phẩm/số lượng gần nhất, xác nhận tồn kho và chuyển sang thu
      thập hồ sơ theo từng bước.
- [ ] Khiếu nại/đổi trả/hàng lỗi tạo ticket ưu tiên cao và dừng bot.
- [ ] Nhân viên tiếp quản có thể tắt/bật bot trên đúng hội thoại; trạng thái
      được ghi audit.
- [ ] Follow-up bỏ giỏ và hỏi đánh giá sau giao hàng không gửi trùng.
- [ ] Chi tiết đơn hàng có đơn vị vận chuyển, mã vận đơn và trạng thái giao hàng;
      không tạo module giao hàng độc lập cho bản này.
- [ ] Palette `Ctrl/Cmd+K` đưa thao tác phổ biến về tối đa ba bước.

## An toàn và vận hành

- [ ] Cấu hình production vượt qua `Settings.validate_runtime()` với HTTPS,
      CORS/host allowlist, HSTS, rate limit và PostgreSQL.
- [ ] Cấu hình ít nhất năm API key cho provider cần xoay vòng; key cũ đã thu hồi
      sau khi xác nhận key mới hoạt động.
- [ ] Token kênh và secret chỉ nằm trong secret manager hoặc `.env` bị ignore.
- [ ] MFA/session/device và audit log đã kiểm tra trên tenant đúng.
- [ ] Backup PostgreSQL đã tạo, restore thử vào staging và đối chiếu row count.
- [ ] `alembic upgrade head` và `alembic check` không báo drift.

## Gate chạy trước phát hành

Từ thư mục gốc:

```powershell
git diff --check
.\scripts\ci-smoke.ps1 -SkipCompose
.\scripts\release-smoke.ps1
```

Nếu Docker Desktop đã chạy, chạy thêm gate compose đầy đủ:

```powershell
.\scripts\ci-smoke.ps1
```

## Kịch bản chấp nhận tối thiểu

1. Gửi `alo` từ từng kênh đang kết nối và kiểm tra lời chào nhất quán.
2. Hỏi một sản phẩm, đổi số lượng, hỏi lại giá; bot không tự yêu cầu dữ liệu
   giao hàng trước khi khách chọn sản phẩm.
3. Nhập tên, số điện thoại, email, địa chỉ thiếu từng phần; bot hỏi đúng phần
   còn thiếu và tạo đơn nháp khi đủ dữ liệu.
4. Gửi khiếu nại hàng lỗi; xác nhận ticket khẩn được tạo và bot không trả lời
   tiếp sau khi nhân viên tiếp quản.
5. Mở lịch sử đơn, cập nhật mã vận đơn/trạng thái, rồi kiểm tra event và
   Unified Timeline có nhãn đúng người thực hiện.
6. Tắt một API key thử nghiệm hoặc mô phỏng lỗi 429; xác nhận request dùng key
   kế tiếp mà log không lộ credential.

## Kế hoạch phát hành

- [ ] Chốt changelog và tag release.
- [ ] Deploy migration trước backend, sau đó deploy backend/worker, cuối cùng
      frontend.
- [ ] Chạy smoke check sau deploy và gửi kết quả cho người duyệt.
- [ ] Theo dõi health, error rate, quota AI, queue follow-up và webhook trong
      30 phút đầu.
- [ ] Nếu rollback, giữ nguyên migration đã chạy; rollback ứng dụng về image
      trước đó và mở incident nếu có mất dữ liệu.
