# Gửi OTP đăng ký bằng Gmail

Luồng đăng ký cần SMTP dùng chung của ứng dụng. SMTP riêng của shop chỉ dùng sau khi shop đã có tài khoản; không thể dùng để xác minh người đăng ký mới.

## Cấu hình an toàn

1. Chọn Gmail dùng riêng để gửi email của ứng dụng, bật xác minh hai bước, rồi tạo mật khẩu ứng dụng tại https://myaccount.google.com/apppasswords. Nếu tài khoản không hỗ trợ mật khẩu ứng dụng, dùng SMTP được nhà cung cấp/tổ chức cho phép; không dùng mật khẩu đăng nhập Gmail thông thường.
2. Đăng nhập quản trị nền tảng, mở **Admin > Email gửi OTP**. Bật **Gmail gửi OTP chung cho hệ thống**, nhập **Gmail gửi**, **Email người gửi** (cùng Gmail gửi), **Tên người gửi** và **Mật khẩu ứng dụng Gmail**, rồi bấm **Lưu cấu hình email**.

Máy chủ Gmail dùng `smtp.gmail.com`, cổng `587`, `STARTTLS`. Mật khẩu ứng dụng nhập một lần, được mã hóa và không hiển thị lại. Khi đã lưu, để trống để giữ nguyên hoặc nhập mật khẩu ứng dụng mới để thay thế. Ô mật khẩu được xóa sau thao tác lưu kể cả khi lỗi; cần kiểm tra thông báo thành công, không coi ô trống là bằng chứng đã lưu.

Không gửi mật khẩu, OTP hoặc ảnh chụp chứa bí mật vào chat hay Git. Khách đăng ký không cần nhập mật khẩu Gmail.

3. Nhập **Email nhận thử**, bấm **Gửi email thử**, kiểm tra Inbox và Spam. Email thử dùng **cấu hình đã lưu**, không dùng thay đổi chưa lưu trên biểu mẫu. Nút chỉ bật khi cấu hình đang bật và đã có mật khẩu. Cấu hình bình thường qua Admin **không cần sửa `.env`, restart hay recreate backend/worker**.
4. Bấm **Gửi mã xác minh** trên màn hình đăng ký một lần, xem cả Inbox và Spam. Nhập mã sáu số, hoàn tất thông tin rồi đăng ký. Mã hết hạn sau 10 phút; yêu cầu lại quá sớm bị giới hạn.

## Kiểm tra lỗi

- Không tải được cấu hình: bấm **Tải lại**, kiểm tra phiên đăng nhập và quyền quản trị nền tảng.
- Lưu lỗi: kiểm tra thông báo và nhập lại mật khẩu ứng dụng nếu cần; mật khẩu vừa nhập đã được xóa khỏi biểu mẫu.
- Không nhận mail: kiểm tra cấu hình đã lưu trong Admin đang bật, Gmail/người gửi đúng và có mật khẩu đã lưu. Chỉ kiểm tra có/không có cấu hình, không in mật khẩu hay OTP vào log.
- SMTP từ chối xác thực: tạo/kiểm tra lại mật khẩu ứng dụng và chính sách tài khoản. Đừng vô hiệu TLS để vượt lỗi.
- Lỗi mạng: kiểm tra DNS và kết nối ra smtp.gmail.com:587 từ backend. Không đánh dấu gửi thành công nếu nhà cung cấp chưa chấp nhận email.
- SMTP chấp nhận email không bảo đảm email đã vào Inbox; lọc spam và hạn mức gửi vẫn do Google quyết định.

Tài liệu chính thức: https://support.google.com/accounts/answer/185833 và https://support.google.com/a/answer/176600.

Không dùng in_chat, bỏ xác minh email hoặc hiển thị OTP trên UI để thay thế việc gửi email thật. Cấu hình thiếu giữ đăng ký ở trạng thái chưa xác minh, không tạo shop giả thành công.

**Trạng thái kiểm chứng:** kiểm thử frontend dùng phản hồi giả lập, không dùng tài khoản Gmail thật hay gửi thư. Chưa kiểm chứng giao thư thực tế vì chưa có mật khẩu ứng dụng Gmail cho lần kiểm tra này. Quản trị viên cần lưu cấu hình và tự gửi email thử để xác nhận.
