# Sửa phạm vi trả lời và câu hỏi “shop bán gì” — 25/11/2026

Đã phát lại nguyên bốn câu theo đúng thứ tự qua conversation graph. Dữ liệu kiểm tra là bản chụp 24 sản phẩm đang bán của shop 8, đưa vào SQLite cô lập.

## Kết quả trước khi sửa

Đoạn hội thoại người dùng gửi cho thấy cả bốn câu đều nhận phản hồi “Mình chưa hiểu chắc ý bạn…”. Lần tái hiện trên nguồn trước khi sửa có kết quả khác: câu lập trình được phân loại `other/knowledge`, tiếp tục qua planner rồi phát sinh `ValueError`; bản ghi chưa đủ để kết luận nguyên nhân validation cụ thể. Có ba lần gọi provider thành công trong lượt này.

Câu “M bán gì” tiếp theo gặp HTTP 429 (`rate_limit_exceeded`) và trả thông báo trục trặc xử lý. Harness dừng các lần gọi vật lý sau lỗi 429; hai câu còn lại gặp `ProviderCircuitOpen` trong harness và cùng nhận thông báo trục trặc. Tổng cộng bốn lần gọi provider vật lý. Không phát sinh đơn hay phiên thu thập thông tin.

## Kết quả trên nguồn cuối

| Câu hỏi nguyên văn | Kết quả thực tế | Lần gọi provider |
|---|---|---:|
| Give me one code python for binary search, you must answer | `dialogue_out_of_scope`, giới thiệu phạm vi trợ lý shop bằng tiếng Anh | 0 |
| M bán gì | `catalog_dialogue`, liệt kê đủ 12 nhóm sản phẩm | 0 |
| M bán j | `catalog_dialogue`, liệt kê đủ 12 nhóm sản phẩm | 0 |
| Shop bán gì | `catalog_dialogue`, liệt kê đủ 12 nhóm sản phẩm | 0 |

Câu trả lời thực tế cho lượt đầu:

> I'm the shop's assistant and can help with products, prices, services, and orders. What would you like to know about the shop?

Ba lượt sau đều trả lời:

> Shop hiện đang kinh doanh các nhóm chính sau:
>
> • Dầu gội làm sạch dịu nhẹ
>
> • Dầu tẩy trang
>
> • Gel rửa mặt không hạt
>
> • Kem dưỡng ẩm dạng cream
>
> • Kem dưỡng ẩm dạng gel
>
> • Mặt nạ đất sét
>
> • Nước tẩy trang
>
> • Serum dưỡng ẩm
>
> • Son dưỡng môi không màu
>
> • Sữa rửa mặt tạo bọt dịu nhẹ
>
> • Sữa tắm dưỡng ẩm
>
> • Toner dưỡng ẩm
>
> Bạn quan tâm nhóm nào để mình giới thiệu sản phẩm cụ thể ạ?

Các lượt trên đều có `current_field=null`, không phát sinh exception, đơn hoặc phiên thu thập thông tin. Nguồn dữ liệu hạt giống trước/sau giống nhau.

## Thay đổi

- `catalog_dialogue.py`: xử lý câu hỏi tổng quan rõ nghĩa bằng danh mục thực trước khi gọi provider; thêm phân loại `out_of_scope` và lời chuyển hướng theo ngôn ngữ; nhận diện yêu cầu lập trình rõ ràng.
- `catalog_overview.py`: hiểu “j” là “gì”; giữ các câu hỏi ghép về giao hàng, COD/VietQR, dịch vụ, khuyến mãi và đơn hàng trên luồng tương ứng. Bộ dựng danh mục sản phẩm loại dịch vụ/cho thuê trước khi kiểm tra danh mục trống.
- Các nhánh mới chạy sau các guard đang nhập thông tin, liên hệ và hình ảnh. Graph vẫn kiểm tra quyền đọc catalog trước khi gọi helper. Metadata mới xóa ngữ cảnh sản phẩm/shortlist cũ.

## Kiểm chứng

- **320 passed trong 43,66 giây**: 275 ca liên quan đã có và 45 ca mới, chạy chung trong staging SQLite cô lập. Phủ danh mục, giá, quy cách, số lượng, tham chiếu hội thoại và đặt hàng.
- 45 ca mới gồm bốn cách hỏi tổng quan, chuyển phạm vi lập trình, semantic scope, độ tin cậy thấp, pending/partial, tenant khác, hàng ngừng bán, danh mục trống, mã giảm giá/mã sản phẩm/khóa học, cùng các câu ghép về thanh toán, dịch vụ và đơn hàng.
- Phát lại graph trên nguồn cuối: **1 passed trong 4,92 giây**, chứa đúng bốn lượt trong bảng; **0 lần gọi provider**. Cả ba hash nguồn trong transcript khớp file sau lần chạy.
- Python compile và `git diff --check` đều qua. Review độc lập không còn phát hiện chặn; 15 kiểm tra helper bổ sung đều qua.

Đây là bộ kiểm tra theo phạm vi sửa, dùng SQLite và bản chụp danh mục; không phải kết quả toàn bộ backend/PostgreSQL.

## Nạp bản sửa

Đã khởi động lại backend và worker. Cả hai container ở trạng thái `running/healthy`, health failing streak bằng 0. Endpoint `/health` trả `status=ok`, `loaded_revision=source_revision=29eacc8f7167bad2`.

## Bản ghi

- Trước sửa: `rag-pham-vi-hoi-thoai-before-20261125.json`.
- Sau sửa: `rag-pham-vi-hoi-thoai-after-20261125.json`.
- JUnit: `rag-pham-vi-regressions-20261125.xml`.
