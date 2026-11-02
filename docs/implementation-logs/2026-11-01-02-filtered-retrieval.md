# 02 — Hard filters trong hybrid retrieval

**Trạng thái:** Hoàn tất hợp đồng retrieval ở tầng dùng chung.

## Đã làm

- `retrieve()` nhận `hard_filters` tùy chọn; hỗ trợ loại đối tượng, một hoặc nhiều SKU, và thuộc tính bắt buộc dạng key/value.
- SKU nhận diện trong câu hỏi được đưa thành điều kiện catalog exact. Predicate dùng `EXISTS` tham số hóa và đặt trước `LIMIT` ở cả truy vấn pgvector và truy vấn BM25.
- Hai nhánh mở rộng parent/neighbor chunk cũng áp lại cùng predicate. Khi truy vấn vector lỗi, lexical fallback vẫn nhận nguyên bộ lọc; không có truy vấn không lọc để bù kết quả.
- Predicate mở rộng chunk được nội suy từ helper allowlist trước khi gửi SQL; giá trị lọc vẫn bind parameter. Chuẩn hóa SKU/giá trị text gom khoảng trắng để catalog, retrieval và serving so sánh cùng một dạng.
- Diagnostics ghi số/tên filter và dimension vector; lỗi lệch dimension được đánh dấu riêng, đồng thời ghi dimension stored nếu thông báo DB cung cấp được.
- Bỏ lọc SKU hậu truy vấn ở Python. Trạng thái/tồn khả dụng không bị đóng cứng trong retrieval; nó được kiểm tra ở bước lấy offer hiện hành.

## Tệp

- `backend/app/rag/catalog_filters.py`
- `backend/app/rag/retriever.py`

## Giới hạn còn lại

- `retrieve()` tự rút các ràng buộc có nhãn rõ (`size`/`kích thước`, `màu`/`color`) và các caller chat/recommendation chuyển `hard_filters` rõ ràng; màu chỉ khớp các alias màu tương đương, không suy đoán sắc độ mơ hồ.
- Tự rút thuộc tính chưa bao phủ mọi key riêng ngành; caller có bộ trích xuất có cấu trúc có thể truyền key/value khác trực tiếp.
- Hard attribute filters yêu cầu chunk được nối với canonical catalog; SKU exact có fallback tương thích legacy bằng cách khớp SKU trong nội dung chunk trước `LIMIT`. Dữ liệu cũ vẫn cần đồng bộ/backfill để dùng typed attributes và trạng thái catalog.

## Kiểm tra

- AST syntax parse tĩnh đã qua cho 24 module nguồn và migration trong lượt rà soát này.
- Đây là ghi chú kiểm tra tĩnh ban đầu; migration và backend suite đã chạy, kết quả runtime nằm bên dưới.

Chưa có tập truy vấn gắn nhãn để đánh giá retrieval ngoài backend suite.

## Kết quả runtime (2026-11-01)

- Migration phụ thuộc cho catalog đã được áp dụng và xác nhận trên 14 tenant.
- Test blend/consent/impression chạy riêng đạt 6/6. Full backend suite chạy lại với allowlist `ALLOWED_HOSTS` hợp lệ và đạt 1,625 passed, 6 skipped, 37 subtests passed.
- Chưa chạy đánh giá retrieval chất lượng trên tập query có nhãn; không có dữ liệu này trong DB hiện tại.

## Kiểm tra cuối

- Kết quả suite: **1,625 passed, 6 skipped, 37 subtests passed**, 9 warnings; PostgreSQL trong Docker; log `2026-11-01-backend-tests-postgres-final.log`.
- Không có tập truy vấn gắn nhãn để tính chất lượng retrieval ngoài các kiểm thử chức năng.
