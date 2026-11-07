# Defect register

Finding trong báo cáo được cập nhật theo kết quả kiểm tra. Bốn lỗi QA-RAG đã có regression offline đạt; chưa retest câu trả lời qua Telegram/provider hoặc runtime đang chạy.

## QA-BLOCK-001 — In-app browser không kết nối localhost

- Loại môi trường, chưa gán lỗi ứng dụng. Priority P1 cho tiến độ E2E.
- Điều kiện ứng dụng trả frontend HTTP 200 từ shell nhưng tab Codex báo ERR_CONNECTION_REFUSED.
- Bước lấy tab http://127.0.0.1:5173/ qua browser automation.
- Kỳ vọng mở được UI. Thực tế browser trả trang lỗi kết nối.
- Evidence browser-blocker.txt; frontend HTTP được ghi riêng. Root cause chưa xác định.
- Đề xuất kiểm tra browser/local-network routing rồi chạy lại E2E. Không bypass security policy.

## QA-RAG-001 — Câu nối tiếp tính tổng chỉ lặp đơn giá

- Medium / P2. FIXED_OFFLINE_REGRESSION_PASS; runtime retest pending.
- Điều kiện catalog Nâng cao 909.000 đồng, tồn 15. Hỏi giá trước rồi “Nếu mua 2 sản phẩm đó thì tổng tiền là bao nhiêu?”.
- Root cause: “nếu/thì” bị giữ lại như từ tên sản phẩm, làm mất nhận diện follow-up chung; formatter cũng chưa tính số lượng trong follow-up.
- Sửa: nhận diện “nếu/thì” là từ nối, lấy số lượng từ câu và nhân đơn giá catalog hiện hành. Trả lời không tạo đơn.
- Evidence: `evidence-20261107/qa-rag-fix-before.log` (3 regression mới fail trước sửa); `evidence-20261107/qa-rag-fix-after-focused.log` (3/3 pass); `evidence-20261107/qa-rag-fix-after-routing-r2.log` (84/84 pass).
- Chưa kiểm tra lại trên Telegram hoặc backend đang chạy.

## QA-RAG-002 — Tên không tồn tại trả danh mục chung

- Medium / P2. FIXED_OFFLINE_REGRESSION_PASS; runtime retest pending.
- Hỏi “Shop có sản phẩm mang tên ZZZ-KHONG-TON-TAI-999 không?”. Expected nêu không tìm thấy hoặc xác minh tên. Actual liệt kê 20 sản phẩm khác.
- Root cause: heuristic liệt kê catalog thắng trước fact lookup có tên sản phẩm; truy vấn tên cụ thể vì vậy mất ràng buộc thực thể.
- Sửa: ưu tiên tra cứu fact cho đối tượng cụ thể; giữ nhánh catalog rộng cho câu hỏi thật sự chung. Không khớp sẽ trả không tìm thấy, không thay bằng danh mục khác.
- Evidence: `evidence-20261107/qa-rag-fix-before.log` (fail trước sửa); `evidence-20261107/qa-rag-fix-after-focused.log` (pass); `evidence-20261107/qa-rag-fix-after-routing-r2.log` (84/84 pass, gồm regression giữ hành vi browse danh mục).
- Chưa kiểm tra lại trên Telegram hoặc backend đang chạy.

## QA-RAG-003 — Hỏi một biến thể trả danh sách rộng

- Medium / P2. FIXED_OFFLINE_REGRESSION_PASS; runtime retest pending.
- Hỏi “Dầu gội dịu nhẹ – Nhỏ gọn giá bao nhiêu và còn mấy sản phẩm?”. Expected 606.000 đồng, tồn 10 cho mẫu đó. Actual trả 20 sản phẩm, có mẫu đúng nhưng dư nhiều nội dung.
- Root cause: từ “còn mấy sản phẩm” được nhận diện như hỏi danh mục rộng; nhánh browse thắng trước tra cứu fact của biến thể.
- Sửa: nhận diện cách hỏi tồn này và ưu tiên exact item lookup trước listing. Regression xác nhận chỉ trả mẫu Nhỏ gọn, giá 606.000 đồng, tồn 10; không lẫn mẫu Nâng cao.
- Evidence: `evidence-20261107/qa-rag-fix-before.log` (fail trước sửa); `evidence-20261107/qa-rag-fix-after-focused.log` (pass); `evidence-20261107/qa-rag-fix-after-routing-r2.log` (84/84 pass).
- Chưa kiểm tra lại trên Telegram hoặc backend đang chạy.

## QA-RAG-004 — Câu liệt kê phòng trọ kèm giá đi nhầm exact product lookup

- Medium / P2. FIXED_OFFLINE_REGRESSION_PASS; runtime retest pending.
- Điều kiện: tenant có `RENTAL_TOOLS`; câu liệt kê phòng kèm giá. Regression tái hiện cả biến thể có typo `bap nhiêu`.
- Root cause: heuristic entity coi từ typo còn lại là tên sản phẩm, khiến exact lookup thắng yêu cầu liệt kê nhiều phòng.
- Sửa: router ưu tiên pattern liệt kê phòng trọ nhiều mục trước heuristic entity; truy vấn phòng đánh số cụ thể vẫn đi exact lookup.
- Evidence: `evidence-20261107/qa-rag-004-retest-before.log` (1 failed); `evidence-20261107/qa-rag-004-retest-after.log` (1 passed); `evidence-20261107/qa-rag-fix-focused-20261107.log` (85 passed); `evidence-20261107/qa-backend-full-fixed-20261107.log` (2,294 passed, 3 skipped, 0 failed).
- Phạm vi: xác nhận luồng offline/định tuyến; chưa chứng minh chất lượng trả lời trên Telegram hoặc runtime.

## QA-OPS-001 — Bundle frontend lớn

- Low / P3. CONFIRMED_CURRENT_BUILD.
- Bước npm run build. Build exit 0 nhưng Vite cảnh báo chunk lớn hơn 500 kB.
- Evidence frontend-build.log. Chưa có LCP/INP để kết luận tác động runtime.
- Đề xuất đo browser baseline trước khi cân nhắc code splitting. Không thay source trong QA.

## QA-PRIV-001 — Consent read/revocation concurrency chưa nghiệm thu

- Rủi ro High / P1, HISTORICAL_OPEN_NOT_REPRODUCED_CURRENT. Không gán đây là exploit mới xác nhận.
- Source báo cáo cũ reports/SMART_MERCHANT_HUB_RELEASE_DECISION.md còn CONSENT_RACE_P2=OPEN.
- Expected hai session revoke/read bảo toàn contract consent. Actual chưa có bằng chứng regression đồng thời chuyên biệt ở lượt này.
- Đề xuất tái hiện trên PostgreSQL disposable với điểm đồng bộ hai session. Không dùng SQLite hoặc static review để đóng finding.

## QA-TEST-001 — Test mặc định vision phụ thuộc cấu hình phát triển

- Medium / P2, CONFIRMED_TEST_ENVIRONMENT_DEPENDENCY. Full suite có 1 failed.
- Bước chạy offline_backend.py khi backend/.env có RAG_IMAGE_CATALOG_MATCH_ENABLED=true.
- Expected ca kiểm default phải đo default có kiểm soát. Actual assert settings flag False gặp True từ .env; class default vẫn False tại config.py dòng 149.
- Bằng chứng backend.log, backend.xml, vision-config-origin.json. Chạy riêng cùng test với biến môi trường false đạt 1/1 ở vision-config-check.log.
- Đề xuất tách rõ kiểm class default và effective config trong test environment. Chỉ ghi nhận; không sửa app/test để đổi kết quả full suite.
