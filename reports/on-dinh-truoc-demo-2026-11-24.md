# Ổn định trước demo — 24/11/2026

Mốc khôi phục trước sửa: `cc1fe20`, tag `checkpoint-before-audit-fixes-20261124`.

## Thay đổi đã thực hiện

- Backend từ chối tiếp tục xử lý/giao đơn khi khoản đã thu đã được hoàn hết; vẫn cho phép nhánh hủy hợp lệ. Không tự sửa lịch sử đơn cũ hoặc đổi quy tắc cộng tồn.
- Đơn đã hủy còn tiền chưa hoàn hiển thị số tiền cần hoàn bằng khoản đã thu trừ khoản đã hoàn.
- Nhãn Telegram/Zalo, thẻ kết nối và badge tổng quan trong modal dùng chung tiêu chí online. Kết nối lưu active nhưng webhook/local device chưa hoạt động được ghi “Đã lưu, chưa hoạt động”.
- Bốn GET cài đặt (hạn mức, tổng hợp chủ đề, lịch chăm sóc, nhật ký) có giới hạn 30 giây và chặn gọi trùng. Bộ lọc lịch chăm sóc bị khóa trong lúc tải; lỗi nhật ký được xử lý thay vì để promise rejection.
- Snapshot hạn mức KB đọc tài liệu chưa xóa và tổng chunk_count từ tenant schema được registry xác nhận active. Tài liệu disabled vẫn chiếm dung lượng. Không ghi đè ledger/reservation trong GET.

## Bằng chứng kiểm tra

- Frontend: 327/327 test đạt sau các sửa đổi cuối.
- Frontend production build đạt; có cảnh báo bundle lớn, không phải lỗi build.
- Backend hoàn tiền/thông báo trạng thái đơn: 7/7 đạt, bao gồm kiểm tra mới chặn đóng gói và giao sau hoàn đủ tiền.
- Backend quota: 9/9 đạt; tái hiện ledger 2/59 trong khi dữ liệu thực 3/77, xác nhận snapshot đúng shop và không sửa ledger.
- RAG seed scope và retrieval audit: 4/4 đạt. Đây là kiểm tra giới hạn; không phải chứng minh mọi câu hỏi chatbot đều đúng.
- git diff --check đạt. Năm dịch vụ runtime (backend, worker, frontend, db, redis) báo healthy trong lượt kiểm tra.
- Các test dùng dữ liệu tổng hợp/SQLite; không thao tác hoàn tiền hoặc gửi thông báo cho khách thật.

## Giới hạn còn phải xác minh

- Công cụ trình duyệt Codex báo “Local browser access is unavailable for this chat”; chưa kiểm chứng trực quan giao diện sau sửa hoặc luồng kênh thật.
- Không bật lại tài liệu RAG cũ: cần xác nhận đúng ngành/shop và chính sách trước. Source đổi tài liệu tắt sang disabled; retrieval lọc ready và business_id. Chưa phát hiện bằng chứng trộn shop trong phần đã rà.
- Ledger quota sau restore vẫn có thể cũ đối với enforcement. Bản sửa snapshot không tự đối soát ledger vì có thể xóa reservation upload đang chạy. Đối soát ghi cần quy trình bảo trì có khóa và dừng ingest, chưa thực hiện trong đợt này.
- Không tự đổi trạng thái hoặc hoàn tồn cho các đơn cũ bất nhất. Cần đối soát đơn cụ thể trước khi chỉnh dữ liệu.
- Các sửa đổi mới chưa commit hoặc push. Mốc khôi phục vẫn giữ nguyên.
