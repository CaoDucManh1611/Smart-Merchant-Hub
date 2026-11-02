# 17 — Sửa marker trích dẫn và lọc thể tích chính xác

**Trạng thái:** Đã cập nhật code trong working tree; chưa commit hoặc push.

## Thay đổi

- Citation gate nhận marker gộp như `[Nguồn 1, Nguồn 2]`, `[Nguồn 1, 2]` và dạng tiếng Anh tương ứng. Mỗi ID vẫn phải nằm trong phạm vi nguồn đã truy xuất; không nới kiểm tra nội dung, giá, SKU hay số liệu. Marker hợp lệ cũng được gỡ khỏi câu khách nhìn thấy.
- Tách dung tích/thể tích khỏi kích thước vật lý. Câu hỏi có đơn vị ml, cl, dl, lít/liter được ánh xạ thành thuộc tính `volume`; size quần áo và kích thước thông thường tiếp tục dùng `size`.
- Đồng bộ catalog có thể lấy `volume` từ nhãn tường minh trong mô tả sản phẩm như “dung tích 1 lít”. Nhập CSV cũng nhận cột volume/capacity/dung tích/thể tích.
- Bộ đồng bộ tài liệu nhận bảng sản phẩm pipe-delimited có cột SKU, tên, giá, tồn; lấy các facet từ header, tạo/sync sản phẩm chuẩn và liên kết chunk theo SKU chính xác. Với sản phẩm đã quản lý thủ công, giá/tồn không bị ghi đè; chỉ bổ sung facet còn thiếu và nối chunk.
- Giữ bộ lọc exact-match trong SQL trước `LIMIT`; không fallback sang tìm chuỗi gần đúng khi thiếu thuộc tính chuẩn hóa.

## Kiểm tra

- `py_compile` cho năm module Python đã sửa: thành công.
- `git diff --check`: thành công; Git chỉ báo cảnh báo chuyển LF/CRLF ở một số file dirty có sẵn.
- Docker Compose hiện có `backend`, `db`, `frontend`, `redis`, `worker` ở trạng thái running. Backend trỏ DB dùng chung `crm_chatbot`, DB nền tảng `crm_platform` và DB tenant `crm_tenant`; không dùng nhầm DB dùng chung để kết luận trạng thái catalog tenant.
- Kiểm tra chỉ đọc DB tenant cho thấy có 14 schema shop với các bảng catalog/recommendation. `shop_4` và `shop_7` đang ở migration `20261101_0015`.
- Snapshot chỉ đọc: `shop_4` có 1 tài liệu, 25 chunks, 1.525 sản phẩm/catalog entries, 25 mapping chunks và 0 thuộc tính `volume`; `shop_7` có 1 tài liệu, 18 chunks, 25 sản phẩm/catalog entries, 29 mapping chunks và 0 thuộc tính `volume`.
- Không chạy pytest, không sửa dữ liệu DB và chưa chạy lại answer pilot. Vì thuộc tính `volume` hiện chưa có trong hai catalog liên quan, chưa thể xác nhận lỗi lọc dung tích đã hết.

## Giới hạn còn lại

- Catalog hiện có không được cập nhật chỉ bằng thay đổi code. Cần xử lý lại tài liệu bảng để tạo mapping/facet và ghi thuộc tính `volume` vào catalog; đến lúc đó hard filter vẫn chủ động trả rỗng nếu thiếu bằng chứng cấu trúc. Việc xử lý lại tài liệu sẽ ghi dữ liệu nên chưa thực hiện.
- Các lỗi thiếu sản phẩm ở shop 4/7 chưa được xác nhận đã hết trên dữ liệu hiện hành. Báo cáo pilot trước đây dùng snapshot câu trả lời cũ, nên không dùng nó để tuyên bố cải thiện điểm.
