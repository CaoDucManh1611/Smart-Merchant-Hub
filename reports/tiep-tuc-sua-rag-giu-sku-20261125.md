# Tiếp tục sửa RAG và giữ đúng SKU — 25/11/2026

## Kết quả sửa

- Chọn dung tích từ câu hiện tại, kể cả `loại100g` và `mặt nạ đất sét100g`; chỉ trả về phiên bản khớp trong nhóm hàng đã xác định.
- Nếu khách yêu cầu quy cách chưa có như 200g, hỏi lại thay vì lấy bản 100g từ lịch sử. Tên nhóm hàng khách vừa nêu được ưu tiên khi chuyển sang nhóm khác.
- Giữ đúng mặt nạ 100g khi khách nói `Cho tôi đặt nó đi` hoặc mua lại theo tên nhóm; yêu cầu rõ 30g vẫn chuyển đúng phiên bản. SKU chứa chuỗi giống dung tích vẫn được xem là mã sản phẩm.
- Thu thập số lượng theo từng sản phẩm. Đổi/thêm món khi đang chờ số lượng không làm mất lựa chọn mới; giỏ có nhiều món vượt tồn kho có thể điều chỉnh lần lượt. Một món đã có số lượng không xác nhận số lượng thay cho món khác.

Các thay đổi tiếp nối nằm ở `backend/app/services/catalog_dialogue.py`, `backend/app/services/customer_collection_flow.py` và các kiểm thử hồi quy tương ứng. Giữ nguyên các thay đổi khác đang có trong workspace, BM25, embedding local và bản rollback về lọc nhu cầu/ngân sách.

## Kiểm chứng

- Bộ kiểm thử tổng hợp: **214 passed**, 97,21 giây. Bao gồm catalog dialogue, 27 ca mặt nạ, product resolver/profile, natural checkout, 12 ca số lượng, cách hỏi nhóm hàng, đơn hàng mới và 22 ca API sản phẩm/đơn hàng. Kết quả JUnit: `reports/rag-checkout-regressions-20261125.xml`.
- Chỉ trong tiến trình pytest: `RUN_POSTGRES_TESTS=0`, `CATALOG_DIALOGUE_ENABLED=false`, `ALLOWED_HOSTS=testserver,localhost,127.0.0.1,backend`; các ca semantic tự bật cờ khi cần. Không sửa allowlist của runtime.
- Kiểm tra cú pháp các service liên quan và `git diff --check` đều đạt. Rà soát độc lập đã xác nhận hai lỗi số lượng được sửa, chưa phát hiện thêm lỗi đáng kể trong phạm vi này.
- Kiểm tra tích hợp với LLM thực tế: **1 passed**, 26,45 giây, 3 lời gọi structured. Chuỗi dữ liệu giả: xem nhóm → đủ 30g và 100g; `Cho xem loại100g` → đúng 100g/189.000đ; `Cho tôi đặt nó đi` → hỏi số lượng cho 100g; `2` → báo giá **378.000đ**. Không có bản ghi Order được tạo.

Các kiểm thử dùng SQLite trong thư mục staging riêng của container; không sửa hội thoại/đơn hàng thật. Kiểm tra LLM chưa chứng minh việc gửi tin qua connector.

## Giới hạn đã ghi nhận

Trong lần so sánh bộ checkout rộng hơn trước vòng rà soát cuối, mã trước và sau sửa đều có cùng **9 lỗi cũ** (2 ca khác đạt), với thông báo trùng nhau. Chúng liên quan kỳ vọng số lượng cũ, tên Serum chồng lấn, tham chiếu ngữ cảnh và OTP; lượt sửa này không xử lý toàn bộ các ca đó. Kết quả 214 ca trên là bộ kiểm chứng liên quan được chọn, không phải toàn bộ backend.

## Runtime sau khi nạp bản sửa

- Đã restart riêng `backend` và `worker` trong project Docker Compose `smart-merchant-hub-runtime`, dùng `docker-compose.yml` và `.git/smh-local.compose.yml`.
- Cả hai container đã được xác nhận **running / healthy**, failing streak bằng 0.
- `http://127.0.0.1:8000/health` trả `status=ok`; `loaded_revision` và `source_revision` cùng bằng **`54e6929f0251c293`**. Backend đã nạp đúng mã nguồn sau sửa.
- Cờ `CATALOG_DIALOGUE_ENABLED` của runtime là `true`; các biến phục vụ pytest chỉ được override trong tiến trình test.
