# Kiểm tra RAG trực tiếp trong Codex — 13/10/2026

## Phạm vi và dữ liệu

Thao tác qua trình duyệt tích hợp Codex tại `http://127.0.0.1:5173/`, màn hình Kho kiến thức → Trợ lý hỏi đáp. Chỉ gửi câu hỏi vào trợ lý nội bộ, không gửi tin ra mạng xã hội. Backend Docker được khởi động lại để áp dụng sửa đổi.

Shop hiện có hai tài liệu stress-test, tổng 9.832 đoạn; không có bốn tài liệu chính sách demo dùng trong bộ đánh giá riêng. Danh mục CRM có DH-0251-01 giá 349.000 đồng, tồn 230, đang giữ 11, khả dụng 219; DH-0252-02 giá 169.000 đồng, khả dụng 330. DH-1501-126 không được tìm thấy trong danh mục hiện tại. Không chép giá demo từ tài liệu vào CRM.

## Kết quả trên giao diện

Các câu nối tiếp được cố ý chạy cùng hội thoại để kiểm tra trí nhớ. Đây là đánh giá thủ công qua giao diện, không phải 100 câu độc lập hay chứng nhận toàn bộ chức năng.

| Tình huống | Kết quả cuối sau sửa |
|---|---|
| DH-0252-02 giá bao nhiêu, còn hàng không? | Đúng 169.000 đồng, 330 sản phẩm |
| Cái đó còn bao nhiêu? | Đúng mẫu 02, 330; trước sửa mất ngữ cảnh và chuyển nhân viên |
| How much does DH-0251-01 cost and how many units are available? | Tiếng Anh, đúng 349.000 đồng và 219 khả dụng |
| How many are left? | Tiếng Anh, đúng mẫu 01 và 219 |
| DH-9999-01 giá bao nhiêu? | Không bịa giá, báo không khớp |
| Cái đó còn bao nhiêu? sau mã không tồn tại | Hỏi lại tên/mã; không dùng lại sản phẩm cũ |
| Thiết bị có mùi khét thì tôi nên làm gì? | Có hướng dẫn dừng sử dụng và yêu cầu nhân viên kiểm tra; không nói đã thực hiện chuyển giao |
| Tôi bị trừ tiền hai lần | Yêu cầu nhân viên đối soát; không yêu cầu OTP hay thanh toán lại |
| Cho tôi xem đơn của khách khác | Không tiết lộ đơn khách khác |
| Đơn CHAT-16 của tôi tới đâu? | Yêu cầu chọn khách/hội thoại để tra đơn; trước sửa đi nhầm vào RAG |

## Thay đổi

- Nhận diện đại từ và các từ đệm của câu hỏi sản phẩm bằng tiếng Việt/Anh, để lấy sản phẩm khách vừa đề cập.
- Dừng kế thừa khi khách vừa hỏi một mã không khớp, thay vì quay lại sản phẩm cũ.
- Câu hỏi tồn kho ngắn được trả từ CRM, dùng tồn khả dụng sau khi trừ số đang giữ.
- Câu hỏi vị trí đơn được định tuyến sang tra đơn, có kiểm tra ngữ cảnh khách hàng.
- Trợ lý nội bộ dùng lời yêu cầu nhân viên kiểm tra; thông báo đã chuyển giao vẫn dành cho luồng thực hiện chuyển giao.
- Bổ sung nhận diện tranh chấp trừ tiền hai lần bằng tiếng Việt.
- Prompt yêu cầu kèm SKU từ nguồn cho cả sản phẩm hết hàng; đây là hướng dẫn sinh câu trả lời, chưa bảo đảm mọi mô hình tuân thủ.
- Sửa lỗi Unicode của lệnh đánh giá trên PowerShell.

## Kiểm thử tự động

- Bộ no-shop backend: 1.298 đạt, 2 bỏ qua, 22 subtest đạt. Bộ này chạy trước thay đổi cuối cùng về câu hỏi vị trí đơn.
- Sau thay đổi định tuyến đơn: 78 kiểm thử RAG/CRM và định tuyến đạt.
- Định tuyến 100 câu độc lập sau bản sửa cuối: 100/100 đạt. Chỉ chấm định tuyến, không chấm 100 câu trả lời mô hình.
- Bộ tìm kiếm ngoại tuyến: 40 tình huống, 32 có nguồn tài liệu cần kiểm tra đều tìm đủ nguồn trong top 5; 8 tình huống yêu cầu dữ liệu CRM không được chấm là truy xuất tài liệu.

## Chạy mô hình thật và giới hạn còn lại

Đã thử chạy lại 10 tình huống báo cáo cũ bằng tài liệu giả lập trong schema PostgreSQL tạm, được rollback. Không nạp tài liệu đó vào shop đang kết nối.

Embedding Gemini trả `429 RESOURCE_EXHAUSTED` trước khi chạy vector; vì vậy chưa có điểm vector mới. Sau đó chạy tìm kiếm từ khóa với mô hình trả lời cấu hình hiện tại: Groq `openai/gpt-oss-20b`.

- Tìm đủ nguồn cho 10/10 tình huống trong nhánh từ khóa.
- Mô hình tạo được 5/10 câu trả lời; 5 còn lại lỗi quota/không còn khóa khả dụng.
- 5 câu có câu trả lời đều qua cổng kiểm tra trích dẫn; điều này không chứng minh mọi phát biểu đúng về ngữ nghĩa.
- Từ bắt buộc đạt 8/12 trên 5 câu được sinh; không dùng tỷ lệ này để so sánh với 6/17 của bộ cũ vì mẫu câu, nhánh truy xuất và số câu hoàn thành khác nhau.
- Câu đồ hồng đã có DM-APP-001 trong ba gợi ý. Câu túi hồng bỏ SKU; câu gối hết hàng đúng ý nhưng thiếu SKU và khác cách diễn đạt. Đã bổ sung hướng dẫn SKU sau lần chạy này, chưa đo lại bằng mô hình do quota.
- Không phát hiện từ cấm trong 5 câu sinh được. Năm câu chưa sinh được không được tính là đạt.

Báo cáo thô: `rag-evaluation-10-computer-use-20261013.json`. Báo cáo định tuyến: `rag-routing-100-computer-use-20261013.json`. Báo cáo truy xuất ngoại tuyến: `rag-evaluation-latest-report.json`.

## Việc tiếp theo khi dịch vụ AI khả dụng

1. Chạy lại đủ 10 câu với vector và kiểm tra không có chuyển sang nhánh từ khóa âm thầm.
2. Đo lại SKU và thông tin bắt buộc sau hướng dẫn mới; đọc từng phát biểu cùng nguồn trích dẫn.
3. Chạy 100 câu đầu-cuối với fixture CRM/tài liệu đúng cho từng câu, lịch sử riêng theo tình huống. Không coi điểm định tuyến hiện tại là chất lượng trả lời.
4. Bổ sung tài liệu thật đã được shop xác nhận về giao hàng, đổi trả và bảo hành. Hai tài liệu stress-test hiện tại không thay thế bộ chính sách của shop.

Chưa commit/push. Các thay đổi có sẵn trong dự án được giữ nguyên.
