# Phân quyền trang quản trị nền tảng

Phân quyền quản trị nền tảng tách riêng khỏi nhân viên và quyền của từng shop. Tài khoản nội bộ dùng email đăng nhập riêng, không được gắn vào dữ liệu của một shop.

## Vai trò

- **Chủ hệ thống**: toàn quyền, gồm quản lý đội ngũ và phân quyền.
- **Vận hành**: tổng quan, quản lý shop, duyệt gói, xem gói dịch vụ, hỗ trợ, kho tư vấn và trạng thái kết nối.
- **Hỗ trợ**: xem shop, xử lý yêu cầu hỗ trợ và xem trạng thái kết nối.
- **Nội dung**: xem gói dịch vụ và quản lý kho tư vấn dịch vụ.
- **Chỉ xem**: xem các mục vận hành được cấp sẵn, không sửa dữ liệu.
- **Tùy chỉnh**: chọn quyền xem, thao tác, tải bản sao và khôi phục theo từng mục.

Quyền thao tác tự bao gồm quyền xem cùng mục. Tải bản sao và khôi phục là hai quyền riêng; quyền xem danh sách sao lưu không cấp quyền tải hoặc khôi phục. Các API quản trị kiểm tra quyền ở máy chủ, kể cả khi người dùng mở URL trực tiếp. Endpoint quản trị mới chưa được phân loại sẽ chỉ dành cho chủ hệ thống.

## Quản lý đội ngũ

Mở **Admin → Đội ngũ & phân quyền** để xem tài khoản nội bộ, tạo tài khoản hoặc sửa vai trò, quyền và trạng thái hoạt động. Tài khoản mới cần email chưa được dùng trong hệ thống và mật khẩu ban đầu đạt chính sách tối thiểu 12 ký tự, có ít nhất ba nhóm ký tự. Ứng dụng không tự gửi email mời; chủ hệ thống cần trao thông tin đăng nhập cho nhân viên qua kênh riêng.

Chỉ chủ hệ thống được tạo hoặc sửa tài khoản quản trị. Người đang đăng nhập không thể tự đổi quyền hay tự khóa mình. Khi quyền hoặc trạng thái tài khoản bị đổi, các phiên đăng nhập trước đó bị thu hồi; nhân viên cần đăng nhập lại. Nhật ký lưu mã người thực hiện, mã tài khoản bị sửa, hành động và thay đổi về vai trò/quyền/trạng thái; không lưu mật khẩu.

## Cập nhật cơ sở dữ liệu

Sau khi triển khai phiên bản này, chạy migration của cơ sở dữ liệu quản trị hiện có rồi khởi động lại API và worker:

```sh
docker compose exec backend python -m alembic -c alembic.ini upgrade head
docker compose restart backend worker
```

Migration thêm vai trò và quyền nội bộ vào `platform_memberships`; các membership hiện có được giữ quyền chủ hệ thống để không làm mất quyền truy cập. Vai trò nhân viên shop không bị thay đổi.
