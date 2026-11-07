# Bộ ca kiểm thử theo rủi ro

96 ca thiết kế cho 16 nhóm. Trạng thái từng ca bên dưới là NOT RUN cho ca thủ công trọn vẹn. Suite tự động đã chạy được kê riêng theo test ID, không tự quy đổi thành toàn bộ ca thủ công PASS.

|ID|Module|Priority|Loại|Điều kiện|Bước thực hiện|Kỳ vọng|Trạng thái|
|---|---|---|---|---|---|---|---|
|AUTH-H|Đăng nhập, OTP, phiên|P0|Happy path|Tài khoản thử và mã OTP mock|Đăng nhập → me → logout → thử token cũ|Đăng nhập hợp lệ thành công; token đã thu hồi bị chặn|NOT RUN|
|AUTH-N|Đăng nhập, OTP, phiên|P0|Negative|Tài khoản thử và mã OTP mock|Thực hiện cùng luồng với trường bắt buộc rỗng, kiểu sai hoặc ID không tồn tại|Lỗi xác định, không ghi dữ liệu dở dang|NOT RUN|
|AUTH-B|Đăng nhập, OTP, phiên|P0|Boundary|Tài khoản thử và mã OTP mock|Thử 0, số âm, giới hạn độ dài/size và vượt giới hạn theo schema OpenAPI|Chấp nhận đúng miền giá trị, từ chối ngoài miền|NOT RUN|
|AUTH-A|Đăng nhập, OTP, phiên|P0|Authorization|Tài khoản thử và mã OTP mock|Thực hiện trực tiếp endpoint bằng token thiếu quyền và token shop khác|Chặn trước tác dụng phụ; dữ liệu shop khác không xuất hiện|NOT RUN|
|AUTH-S|Đăng nhập, OTP, phiên|P0|State/idempotency|Tài khoản thử và mã OTP mock|Lặp cùng yêu cầu và thử chuyển trạng thái sai; kiểm dữ liệu trước/sau|Không nhân đôi tác dụng, rollback khi lỗi|NOT RUN|
|AUTH-R|Đăng nhập, OTP, phiên|P0|Reliability|Tài khoản thử và mã OTP mock|Trong môi trường cô lập, giả lập dependency timeout/failure và thử khôi phục|Lỗi có kiểm soát; retry hữu hạn, không gửi/giao dịch trùng|NOT RUN|
|RBAC-H|Vai trò và tenant|P0|Happy path|Hai shop thử, owner và agent|Dùng từng vai trò đọc/ghi ID shop khác qua API|Đúng quyền; ID shop khác bị chặn, không đổi dữ liệu|NOT RUN|
|RBAC-N|Vai trò và tenant|P0|Negative|Hai shop thử, owner và agent|Thực hiện cùng luồng với trường bắt buộc rỗng, kiểu sai hoặc ID không tồn tại|Lỗi xác định, không ghi dữ liệu dở dang|NOT RUN|
|RBAC-B|Vai trò và tenant|P0|Boundary|Hai shop thử, owner và agent|Thử 0, số âm, giới hạn độ dài/size và vượt giới hạn theo schema OpenAPI|Chấp nhận đúng miền giá trị, từ chối ngoài miền|NOT RUN|
|RBAC-A|Vai trò và tenant|P0|Authorization|Hai shop thử, owner và agent|Thực hiện trực tiếp endpoint bằng token thiếu quyền và token shop khác|Chặn trước tác dụng phụ; dữ liệu shop khác không xuất hiện|NOT RUN|
|RBAC-S|Vai trò và tenant|P0|State/idempotency|Hai shop thử, owner và agent|Lặp cùng yêu cầu và thử chuyển trạng thái sai; kiểm dữ liệu trước/sau|Không nhân đôi tác dụng, rollback khi lỗi|NOT RUN|
|RBAC-R|Vai trò và tenant|P0|Reliability|Hai shop thử, owner và agent|Trong môi trường cô lập, giả lập dependency timeout/failure và thử khôi phục|Lỗi có kiểm soát; retry hữu hạn, không gửi/giao dịch trùng|NOT RUN|
|CRM-H|Khách, danh tính, gộp|P1|Happy path|Hai hồ sơ thử có lịch sử|Tìm kiếm → xem 360 → merge preview → merge → undo|Tìm đúng; chuyển liên kết và hoàn tác có audit|NOT RUN|
|CRM-N|Khách, danh tính, gộp|P1|Negative|Hai hồ sơ thử có lịch sử|Thực hiện cùng luồng với trường bắt buộc rỗng, kiểu sai hoặc ID không tồn tại|Lỗi xác định, không ghi dữ liệu dở dang|NOT RUN|
|CRM-B|Khách, danh tính, gộp|P1|Boundary|Hai hồ sơ thử có lịch sử|Thử 0, số âm, giới hạn độ dài/size và vượt giới hạn theo schema OpenAPI|Chấp nhận đúng miền giá trị, từ chối ngoài miền|NOT RUN|
|CRM-A|Khách, danh tính, gộp|P1|Authorization|Hai hồ sơ thử có lịch sử|Thực hiện trực tiếp endpoint bằng token thiếu quyền và token shop khác|Chặn trước tác dụng phụ; dữ liệu shop khác không xuất hiện|NOT RUN|
|CRM-S|Khách, danh tính, gộp|P1|State/idempotency|Hai hồ sơ thử có lịch sử|Lặp cùng yêu cầu và thử chuyển trạng thái sai; kiểm dữ liệu trước/sau|Không nhân đôi tác dụng, rollback khi lỗi|NOT RUN|
|CRM-R|Khách, danh tính, gộp|P1|Reliability|Hai hồ sơ thử có lịch sử|Trong môi trường cô lập, giả lập dependency timeout/failure và thử khôi phục|Lỗi có kiểm soát; retry hữu hạn, không gửi/giao dịch trùng|NOT RUN|
|INBOX-H|Hội thoại, realtime, media|P1|Happy path|Kênh sandbox và hội thoại thử|Nhận sự kiện → mở chat → gửi phản hồi → refresh|Không trùng, giữ thời gian/thứ tự, trạng thái gửi đúng|NOT RUN|
|INBOX-N|Hội thoại, realtime, media|P1|Negative|Kênh sandbox và hội thoại thử|Thực hiện cùng luồng với trường bắt buộc rỗng, kiểu sai hoặc ID không tồn tại|Lỗi xác định, không ghi dữ liệu dở dang|NOT RUN|
|INBOX-B|Hội thoại, realtime, media|P1|Boundary|Kênh sandbox và hội thoại thử|Thử 0, số âm, giới hạn độ dài/size và vượt giới hạn theo schema OpenAPI|Chấp nhận đúng miền giá trị, từ chối ngoài miền|NOT RUN|
|INBOX-A|Hội thoại, realtime, media|P1|Authorization|Kênh sandbox và hội thoại thử|Thực hiện trực tiếp endpoint bằng token thiếu quyền và token shop khác|Chặn trước tác dụng phụ; dữ liệu shop khác không xuất hiện|NOT RUN|
|INBOX-S|Hội thoại, realtime, media|P1|State/idempotency|Kênh sandbox và hội thoại thử|Lặp cùng yêu cầu và thử chuyển trạng thái sai; kiểm dữ liệu trước/sau|Không nhân đôi tác dụng, rollback khi lỗi|NOT RUN|
|INBOX-R|Hội thoại, realtime, media|P1|Reliability|Kênh sandbox và hội thoại thử|Trong môi trường cô lập, giả lập dependency timeout/failure và thử khôi phục|Lỗi có kiểm soát; retry hữu hạn, không gửi/giao dịch trùng|NOT RUN|
|CHANNEL-H|Meta, Telegram, Zalo, TikTok, Shopee|P0|Happy path|Provider giả lập; kênh thật cần sandbox riêng|Verify chữ ký → nhận sự kiện → phát lại → sai chữ ký|Lưu hợp lệ một lần, chữ ký sai bị từ chối|NOT RUN|
|CHANNEL-N|Meta, Telegram, Zalo, TikTok, Shopee|P0|Negative|Provider giả lập; kênh thật cần sandbox riêng|Thực hiện cùng luồng với trường bắt buộc rỗng, kiểu sai hoặc ID không tồn tại|Lỗi xác định, không ghi dữ liệu dở dang|NOT RUN|
|CHANNEL-B|Meta, Telegram, Zalo, TikTok, Shopee|P0|Boundary|Provider giả lập; kênh thật cần sandbox riêng|Thử 0, số âm, giới hạn độ dài/size và vượt giới hạn theo schema OpenAPI|Chấp nhận đúng miền giá trị, từ chối ngoài miền|NOT RUN|
|CHANNEL-A|Meta, Telegram, Zalo, TikTok, Shopee|P0|Authorization|Provider giả lập; kênh thật cần sandbox riêng|Thực hiện trực tiếp endpoint bằng token thiếu quyền và token shop khác|Chặn trước tác dụng phụ; dữ liệu shop khác không xuất hiện|NOT RUN|
|CHANNEL-S|Meta, Telegram, Zalo, TikTok, Shopee|P0|State/idempotency|Provider giả lập; kênh thật cần sandbox riêng|Lặp cùng yêu cầu và thử chuyển trạng thái sai; kiểm dữ liệu trước/sau|Không nhân đôi tác dụng, rollback khi lỗi|NOT RUN|
|CHANNEL-R|Meta, Telegram, Zalo, TikTok, Shopee|P0|Reliability|Provider giả lập; kênh thật cần sandbox riêng|Trong môi trường cô lập, giả lập dependency timeout/failure và thử khôi phục|Lỗi có kiểm soát; retry hữu hạn, không gửi/giao dịch trùng|NOT RUN|
|CATALOG-H|Sản phẩm, ảnh, nhập CSV|P1|Happy path|Sản phẩm demo riêng, CSV thử|Nhập → đọc giá/tồn → thay ảnh → chỉnh tồn|Đúng đơn vị, chống nhập lặp, ảnh đọc được|NOT RUN|
|CATALOG-N|Sản phẩm, ảnh, nhập CSV|P1|Negative|Sản phẩm demo riêng, CSV thử|Thực hiện cùng luồng với trường bắt buộc rỗng, kiểu sai hoặc ID không tồn tại|Lỗi xác định, không ghi dữ liệu dở dang|NOT RUN|
|CATALOG-B|Sản phẩm, ảnh, nhập CSV|P1|Boundary|Sản phẩm demo riêng, CSV thử|Thử 0, số âm, giới hạn độ dài/size và vượt giới hạn theo schema OpenAPI|Chấp nhận đúng miền giá trị, từ chối ngoài miền|NOT RUN|
|CATALOG-A|Sản phẩm, ảnh, nhập CSV|P1|Authorization|Sản phẩm demo riêng, CSV thử|Thực hiện trực tiếp endpoint bằng token thiếu quyền và token shop khác|Chặn trước tác dụng phụ; dữ liệu shop khác không xuất hiện|NOT RUN|
|CATALOG-S|Sản phẩm, ảnh, nhập CSV|P1|State/idempotency|Sản phẩm demo riêng, CSV thử|Lặp cùng yêu cầu và thử chuyển trạng thái sai; kiểm dữ liệu trước/sau|Không nhân đôi tác dụng, rollback khi lỗi|NOT RUN|
|CATALOG-R|Sản phẩm, ảnh, nhập CSV|P1|Reliability|Sản phẩm demo riêng, CSV thử|Trong môi trường cô lập, giả lập dependency timeout/failure và thử khôi phục|Lỗi có kiểm soát; retry hữu hạn, không gửi/giao dịch trùng|NOT RUN|
|ORDER-H|Đơn bán, tồn, thanh toán đơn|P0|Happy path|Sản phẩm/khách/đơn thử|Tạo nháp → xác nhận → giao → hoàn tất → gửi lại thao tác|Trạng thái hợp lệ; tồn và khoản thu không nhân đôi|NOT RUN|
|ORDER-N|Đơn bán, tồn, thanh toán đơn|P0|Negative|Sản phẩm/khách/đơn thử|Thực hiện cùng luồng với trường bắt buộc rỗng, kiểu sai hoặc ID không tồn tại|Lỗi xác định, không ghi dữ liệu dở dang|NOT RUN|
|ORDER-B|Đơn bán, tồn, thanh toán đơn|P0|Boundary|Sản phẩm/khách/đơn thử|Thử 0, số âm, giới hạn độ dài/size và vượt giới hạn theo schema OpenAPI|Chấp nhận đúng miền giá trị, từ chối ngoài miền|NOT RUN|
|ORDER-A|Đơn bán, tồn, thanh toán đơn|P0|Authorization|Sản phẩm/khách/đơn thử|Thực hiện trực tiếp endpoint bằng token thiếu quyền và token shop khác|Chặn trước tác dụng phụ; dữ liệu shop khác không xuất hiện|NOT RUN|
|ORDER-S|Đơn bán, tồn, thanh toán đơn|P0|State/idempotency|Sản phẩm/khách/đơn thử|Lặp cùng yêu cầu và thử chuyển trạng thái sai; kiểm dữ liệu trước/sau|Không nhân đôi tác dụng, rollback khi lỗi|NOT RUN|
|ORDER-R|Đơn bán, tồn, thanh toán đơn|P0|Reliability|Sản phẩm/khách/đơn thử|Trong môi trường cô lập, giả lập dependency timeout/failure và thử khôi phục|Lỗi có kiểm soát; retry hữu hạn, không gửi/giao dịch trùng|NOT RUN|
|PROCURE-H|Nhà cung cấp, mua hàng, kho|P0|Happy path|Đơn mua thử|Tạo đơn → nhận một phần → nhận còn lại → gửi lặp|Tồn chỉ tăng theo lượng nhận mới; có ledger|NOT RUN|
|PROCURE-N|Nhà cung cấp, mua hàng, kho|P0|Negative|Đơn mua thử|Thực hiện cùng luồng với trường bắt buộc rỗng, kiểu sai hoặc ID không tồn tại|Lỗi xác định, không ghi dữ liệu dở dang|NOT RUN|
|PROCURE-B|Nhà cung cấp, mua hàng, kho|P0|Boundary|Đơn mua thử|Thử 0, số âm, giới hạn độ dài/size và vượt giới hạn theo schema OpenAPI|Chấp nhận đúng miền giá trị, từ chối ngoài miền|NOT RUN|
|PROCURE-A|Nhà cung cấp, mua hàng, kho|P0|Authorization|Đơn mua thử|Thực hiện trực tiếp endpoint bằng token thiếu quyền và token shop khác|Chặn trước tác dụng phụ; dữ liệu shop khác không xuất hiện|NOT RUN|
|PROCURE-S|Nhà cung cấp, mua hàng, kho|P0|State/idempotency|Đơn mua thử|Lặp cùng yêu cầu và thử chuyển trạng thái sai; kiểm dữ liệu trước/sau|Không nhân đôi tác dụng, rollback khi lỗi|NOT RUN|
|PROCURE-R|Nhà cung cấp, mua hàng, kho|P0|Reliability|Đơn mua thử|Trong môi trường cô lập, giả lập dependency timeout/failure và thử khôi phục|Lỗi có kiểm soát; retry hữu hạn, không gửi/giao dịch trùng|NOT RUN|
|SERVICE-H|Dịch vụ, lịch hẹn, giờ làm|P1|Happy path|Dịch vụ và ca làm thử|Tra lịch → đặt thử → đổi trạng thái → sửa ghi chú khi capability tắt|Không đặt nhầm khi tra lịch; không bật lại reminder|NOT RUN|
|SERVICE-N|Dịch vụ, lịch hẹn, giờ làm|P1|Negative|Dịch vụ và ca làm thử|Thực hiện cùng luồng với trường bắt buộc rỗng, kiểu sai hoặc ID không tồn tại|Lỗi xác định, không ghi dữ liệu dở dang|NOT RUN|
|SERVICE-B|Dịch vụ, lịch hẹn, giờ làm|P1|Boundary|Dịch vụ và ca làm thử|Thử 0, số âm, giới hạn độ dài/size và vượt giới hạn theo schema OpenAPI|Chấp nhận đúng miền giá trị, từ chối ngoài miền|NOT RUN|
|SERVICE-A|Dịch vụ, lịch hẹn, giờ làm|P1|Authorization|Dịch vụ và ca làm thử|Thực hiện trực tiếp endpoint bằng token thiếu quyền và token shop khác|Chặn trước tác dụng phụ; dữ liệu shop khác không xuất hiện|NOT RUN|
|SERVICE-S|Dịch vụ, lịch hẹn, giờ làm|P1|State/idempotency|Dịch vụ và ca làm thử|Lặp cùng yêu cầu và thử chuyển trạng thái sai; kiểm dữ liệu trước/sau|Không nhân đôi tác dụng, rollback khi lỗi|NOT RUN|
|SERVICE-R|Dịch vụ, lịch hẹn, giờ làm|P1|Reliability|Dịch vụ và ca làm thử|Trong môi trường cô lập, giả lập dependency timeout/failure và thử khôi phục|Lỗi có kiểm soát; retry hữu hạn, không gửi/giao dịch trùng|NOT RUN|
|KB-H|Tài liệu, parsing, version, index|P0|Happy path|Tài liệu thử có cụm từ đối chứng|Upload → chờ ready → retrieve → replace → rollback trong DB thử|Đúng nguồn/version/tenant; publish và rollback nhất quán|NOT RUN|
|KB-N|Tài liệu, parsing, version, index|P0|Negative|Tài liệu thử có cụm từ đối chứng|Thực hiện cùng luồng với trường bắt buộc rỗng, kiểu sai hoặc ID không tồn tại|Lỗi xác định, không ghi dữ liệu dở dang|NOT RUN|
|KB-B|Tài liệu, parsing, version, index|P0|Boundary|Tài liệu thử có cụm từ đối chứng|Thử 0, số âm, giới hạn độ dài/size và vượt giới hạn theo schema OpenAPI|Chấp nhận đúng miền giá trị, từ chối ngoài miền|NOT RUN|
|KB-A|Tài liệu, parsing, version, index|P0|Authorization|Tài liệu thử có cụm từ đối chứng|Thực hiện trực tiếp endpoint bằng token thiếu quyền và token shop khác|Chặn trước tác dụng phụ; dữ liệu shop khác không xuất hiện|NOT RUN|
|KB-S|Tài liệu, parsing, version, index|P0|State/idempotency|Tài liệu thử có cụm từ đối chứng|Lặp cùng yêu cầu và thử chuyển trạng thái sai; kiểm dữ liệu trước/sau|Không nhân đôi tác dụng, rollback khi lỗi|NOT RUN|
|KB-R|Tài liệu, parsing, version, index|P0|Reliability|Tài liệu thử có cụm từ đối chứng|Trong môi trường cô lập, giả lập dependency timeout/failure và thử khôi phục|Lỗi có kiểm soát; retry hữu hạn, không gửi/giao dịch trùng|NOT RUN|
|RAG-H|Graph, nguồn, tư vấn, multi-turn|P0|Happy path|Catalog và evidence cố định, model mock|Hỏi giá → nối tiếp → đổi mẫu → thiếu nguồn → injection|Dữ kiện khớp nguồn; hỏi lại khi cần; tool được cấp quyền|NOT RUN|
|RAG-N|Graph, nguồn, tư vấn, multi-turn|P0|Negative|Catalog và evidence cố định, model mock|Thực hiện cùng luồng với trường bắt buộc rỗng, kiểu sai hoặc ID không tồn tại|Lỗi xác định, không ghi dữ liệu dở dang|NOT RUN|
|RAG-B|Graph, nguồn, tư vấn, multi-turn|P0|Boundary|Catalog và evidence cố định, model mock|Thử 0, số âm, giới hạn độ dài/size và vượt giới hạn theo schema OpenAPI|Chấp nhận đúng miền giá trị, từ chối ngoài miền|NOT RUN|
|RAG-A|Graph, nguồn, tư vấn, multi-turn|P0|Authorization|Catalog và evidence cố định, model mock|Thực hiện trực tiếp endpoint bằng token thiếu quyền và token shop khác|Chặn trước tác dụng phụ; dữ liệu shop khác không xuất hiện|NOT RUN|
|RAG-S|Graph, nguồn, tư vấn, multi-turn|P0|State/idempotency|Catalog và evidence cố định, model mock|Lặp cùng yêu cầu và thử chuyển trạng thái sai; kiểm dữ liệu trước/sau|Không nhân đôi tác dụng, rollback khi lỗi|NOT RUN|
|RAG-R|Graph, nguồn, tư vấn, multi-turn|P0|Reliability|Catalog và evidence cố định, model mock|Trong môi trường cô lập, giả lập dependency timeout/failure và thử khôi phục|Lỗi có kiểm soát; retry hữu hạn, không gửi/giao dịch trùng|NOT RUN|
|RFM-H|RFM, recommendation, consent|P0|Happy path|Khách mới, consented, từ chối và revoked|Gợi ý cùng nhu cầu/ngân sách với từng persona|Chỉ dùng history được phép; không lộ shop; không bịa propensity|NOT RUN|
|RFM-N|RFM, recommendation, consent|P0|Negative|Khách mới, consented, từ chối và revoked|Thực hiện cùng luồng với trường bắt buộc rỗng, kiểu sai hoặc ID không tồn tại|Lỗi xác định, không ghi dữ liệu dở dang|NOT RUN|
|RFM-B|RFM, recommendation, consent|P0|Boundary|Khách mới, consented, từ chối và revoked|Thử 0, số âm, giới hạn độ dài/size và vượt giới hạn theo schema OpenAPI|Chấp nhận đúng miền giá trị, từ chối ngoài miền|NOT RUN|
|RFM-A|RFM, recommendation, consent|P0|Authorization|Khách mới, consented, từ chối và revoked|Thực hiện trực tiếp endpoint bằng token thiếu quyền và token shop khác|Chặn trước tác dụng phụ; dữ liệu shop khác không xuất hiện|NOT RUN|
|RFM-S|RFM, recommendation, consent|P0|State/idempotency|Khách mới, consented, từ chối và revoked|Lặp cùng yêu cầu và thử chuyển trạng thái sai; kiểm dữ liệu trước/sau|Không nhân đôi tác dụng, rollback khi lỗi|NOT RUN|
|RFM-R|RFM, recommendation, consent|P0|Reliability|Khách mới, consented, từ chối và revoked|Trong môi trường cô lập, giả lập dependency timeout/failure và thử khôi phục|Lỗi có kiểm soát; retry hữu hạn, không gửi/giao dịch trùng|NOT RUN|
|WORK-H|Tickets, SLA, tasks, workflow|P1|Happy path|Hội thoại và ticket thử|Tạo → phân công → quá hạn → đóng → dispatch bị chặn|SLA/trạng thái/job đúng; không gửi khi bị chặn|NOT RUN|
|WORK-N|Tickets, SLA, tasks, workflow|P1|Negative|Hội thoại và ticket thử|Thực hiện cùng luồng với trường bắt buộc rỗng, kiểu sai hoặc ID không tồn tại|Lỗi xác định, không ghi dữ liệu dở dang|NOT RUN|
|WORK-B|Tickets, SLA, tasks, workflow|P1|Boundary|Hội thoại và ticket thử|Thử 0, số âm, giới hạn độ dài/size và vượt giới hạn theo schema OpenAPI|Chấp nhận đúng miền giá trị, từ chối ngoài miền|NOT RUN|
|WORK-A|Tickets, SLA, tasks, workflow|P1|Authorization|Hội thoại và ticket thử|Thực hiện trực tiếp endpoint bằng token thiếu quyền và token shop khác|Chặn trước tác dụng phụ; dữ liệu shop khác không xuất hiện|NOT RUN|
|WORK-S|Tickets, SLA, tasks, workflow|P1|State/idempotency|Hội thoại và ticket thử|Lặp cùng yêu cầu và thử chuyển trạng thái sai; kiểm dữ liệu trước/sau|Không nhân đôi tác dụng, rollback khi lỗi|NOT RUN|
|WORK-R|Tickets, SLA, tasks, workflow|P1|Reliability|Hội thoại và ticket thử|Trong môi trường cô lập, giả lập dependency timeout/failure và thử khôi phục|Lỗi có kiểm soát; retry hữu hạn, không gửi/giao dịch trùng|NOT RUN|
|SAAS-H|Shop, team, gói, thu phí|P0|Happy path|Platform admin thử; payment mock|Đăng ký gói → xác nhận tiền → approve → retry callback|Chỉ kích hoạt khi đủ điều kiện; khoản thu không trùng|NOT RUN|
|SAAS-N|Shop, team, gói, thu phí|P0|Negative|Platform admin thử; payment mock|Thực hiện cùng luồng với trường bắt buộc rỗng, kiểu sai hoặc ID không tồn tại|Lỗi xác định, không ghi dữ liệu dở dang|NOT RUN|
|SAAS-B|Shop, team, gói, thu phí|P0|Boundary|Platform admin thử; payment mock|Thử 0, số âm, giới hạn độ dài/size và vượt giới hạn theo schema OpenAPI|Chấp nhận đúng miền giá trị, từ chối ngoài miền|NOT RUN|
|SAAS-A|Shop, team, gói, thu phí|P0|Authorization|Platform admin thử; payment mock|Thực hiện trực tiếp endpoint bằng token thiếu quyền và token shop khác|Chặn trước tác dụng phụ; dữ liệu shop khác không xuất hiện|NOT RUN|
|SAAS-S|Shop, team, gói, thu phí|P0|State/idempotency|Platform admin thử; payment mock|Lặp cùng yêu cầu và thử chuyển trạng thái sai; kiểm dữ liệu trước/sau|Không nhân đôi tác dụng, rollback khi lỗi|NOT RUN|
|SAAS-R|Shop, team, gói, thu phí|P0|Reliability|Platform admin thử; payment mock|Trong môi trường cô lập, giả lập dependency timeout/failure và thử khôi phục|Lỗi có kiểm soát; retry hữu hạn, không gửi/giao dịch trùng|NOT RUN|
|PRIVACY-H|Consent, purge, nhật ký|P0|Happy path|Dữ liệu thử có consent và metadata|Revoke → đọc/ghi memory → purge scoped → kiểm audit|Chặn dữ liệu bị thu hồi; purge đúng phạm vi; race cần PG|NOT RUN|
|PRIVACY-N|Consent, purge, nhật ký|P0|Negative|Dữ liệu thử có consent và metadata|Thực hiện cùng luồng với trường bắt buộc rỗng, kiểu sai hoặc ID không tồn tại|Lỗi xác định, không ghi dữ liệu dở dang|NOT RUN|
|PRIVACY-B|Consent, purge, nhật ký|P0|Boundary|Dữ liệu thử có consent và metadata|Thử 0, số âm, giới hạn độ dài/size và vượt giới hạn theo schema OpenAPI|Chấp nhận đúng miền giá trị, từ chối ngoài miền|NOT RUN|
|PRIVACY-A|Consent, purge, nhật ký|P0|Authorization|Dữ liệu thử có consent và metadata|Thực hiện trực tiếp endpoint bằng token thiếu quyền và token shop khác|Chặn trước tác dụng phụ; dữ liệu shop khác không xuất hiện|NOT RUN|
|PRIVACY-S|Consent, purge, nhật ký|P0|State/idempotency|Dữ liệu thử có consent và metadata|Lặp cùng yêu cầu và thử chuyển trạng thái sai; kiểm dữ liệu trước/sau|Không nhân đôi tác dụng, rollback khi lỗi|NOT RUN|
|PRIVACY-R|Consent, purge, nhật ký|P0|Reliability|Dữ liệu thử có consent và metadata|Trong môi trường cô lập, giả lập dependency timeout/failure và thử khôi phục|Lỗi có kiểm soát; retry hữu hạn, không gửi/giao dịch trùng|NOT RUN|
|OPS-H|Báo cáo, backup, vận hành|P0|Happy path|DB disposable và bản sao lưu thử|Build → health → backup → verify → restore → so hash|Build được; báo cáo đúng kỳ; restore có kiểm chứng|NOT RUN|
|OPS-N|Báo cáo, backup, vận hành|P0|Negative|DB disposable và bản sao lưu thử|Thực hiện cùng luồng với trường bắt buộc rỗng, kiểu sai hoặc ID không tồn tại|Lỗi xác định, không ghi dữ liệu dở dang|NOT RUN|
|OPS-B|Báo cáo, backup, vận hành|P0|Boundary|DB disposable và bản sao lưu thử|Thử 0, số âm, giới hạn độ dài/size và vượt giới hạn theo schema OpenAPI|Chấp nhận đúng miền giá trị, từ chối ngoài miền|NOT RUN|
|OPS-A|Báo cáo, backup, vận hành|P0|Authorization|DB disposable và bản sao lưu thử|Thực hiện trực tiếp endpoint bằng token thiếu quyền và token shop khác|Chặn trước tác dụng phụ; dữ liệu shop khác không xuất hiện|NOT RUN|
|OPS-S|Báo cáo, backup, vận hành|P0|State/idempotency|DB disposable và bản sao lưu thử|Lặp cùng yêu cầu và thử chuyển trạng thái sai; kiểm dữ liệu trước/sau|Không nhân đôi tác dụng, rollback khi lỗi|NOT RUN|
|OPS-R|Báo cáo, backup, vận hành|P0|Reliability|DB disposable và bản sao lưu thử|Trong môi trường cô lập, giả lập dependency timeout/failure và thử khôi phục|Lỗi có kiểm soát; retry hữu hạn, không gửi/giao dịch trùng|NOT RUN|

## Theo dõi API và AI

405 operations nằm trong api-inventory.json, mặc định NOT_RUN. Với mỗi operation cần lần lượt token/role hợp lệ, thiếu token, token hỏng/hết hạn, tenant khác, body thiếu/sai kiểu, biên, pagination và dependency failure theo schema thực tế. Body và assertion cụ thể của test hiện có nằm trong JUnit/test source.

AI dùng catalog và nguồn giả lập đóng băng. Các ca tối thiểu gồm giá/tồn, ngân sách, so sánh, câu nối tiếp, đổi mẫu, sai chính tả, variant gần nhau, hết hàng, không tồn tại, không có chính sách, injection trong KB, tenant khác, consent revoked và tool bị tắt. Kỳ vọng lấy từ snapshot; chấm factual correctness, grounding, helpfulness và unsupported claims trên từng ca. Chưa chạy model mới trong lượt QA này.
