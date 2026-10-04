# File mẫu nhập danh mục và đơn bán

Trong CRM, mở **Sản phẩm → Tải file mẫu sản phẩm** hoặc **Đơn bán → Nhập CSV đơn hàng → Tải file mẫu đơn bán**. Hai tệp này thuộc dự án và bám theo API import hiện có; dòng ví dụ chỉ để hướng dẫn, cần thay bằng dữ liệu thật trước khi nhập.

## Sản phẩm

`frontend/public/templates/product-import-template.csv` dùng tiêu đề tiếng Việt mà API sản phẩm nhận diện. Cần điền mã sản phẩm, tên, giá và tồn kho. `Link sản phẩm` là tùy chọn, chỉ nhận HTTP(S); bỏ trống nếu chưa có. Khi nhập lại một mã sản phẩm đã tồn tại, quy trình import có thể cập nhật/cộng tồn theo logic của API, vì vậy phải xem trước nội dung trước khi xác nhận.

## Đơn bán

`frontend/public/templates/order-import-template.csv` dùng đúng các cột `order_number,customer_id,sku,quantity,conversation_id`. Bốn cột đầu bắt buộc; `conversation_id` có thể để trống. `customer_id` phải là ID khách có thật trong cùng shop và `sku` phải có trong danh mục. Mỗi dòng là một sản phẩm; nhiều dòng cùng `order_number` tạo một đơn, với cùng `customer_id` và `conversation_id`.

CRM có bước **Xem trước** để báo lỗi theo dòng trước khi ghi. Đơn được nhập ở trạng thái **nháp**, tính theo giá hiện tại trong danh mục; không tự xác nhận, thanh toán hay trừ tồn. Không dùng dữ liệu khách thật trong file mẫu hoặc ảnh bàn giao.
