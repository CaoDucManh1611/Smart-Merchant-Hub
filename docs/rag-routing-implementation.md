# Shared routing implementation

## Applied
- Serving records and consumes the same classify_intent result for catalog selection.
- Explicit handoff takes precedence over order/product processing and uses existing notification flow.
- Private customer/tenant boundaries remain in existing tool handlers.
- Removed sample skincare SKU/name triggers and duplicate fallback from shared router.
- Policy and mixed product+delivery requests stay on knowledge route.
- No generic router output directly authorizes order creation, payment or booking.

## Validation
129 focused component/contract tests passed, including multi-intent policy, catalog+price, explicit staff request, and appointment/payment information requests.

## Boundaries still requiring further work
The product, order and collection handlers still contain their own domain predicates. Full consolidation and removal of all legacy industry heuristics is not complete. Ambiguous references and multi-intent responses need database-backed and external-channel acceptance before production approval.

## Tham khảo kiến trúc và sửa định tuyến (2026-10-23)

Nguồn tham khảo: LangGraph customer support (https://github.com/langchain-ai/docs/blob/main/src/oss/langgraph/thinking-in-langgraph.mdx), Haystack ConditionalRouter (https://docs.haystack.deepset.ai/docs/conditionalrouter).
Áp dụng nguyên tắc tách quyết định điều hướng khỏi nội dung trả lời và kiểm tra điều kiện trước nhánh tổng quát; không thêm framework mới.

- Bỏ nhánh trả giá/tồn kho cho mọi câu chứa số phòng, vốn nuốt câu hỏi tiện ích/chính sách.
- Phân biệt câu hỏi một đối tượng có thuộc tính với yêu cầu tìm đối tượng đang bán.
- Câu hỏi có tên/mã chính xác được bổ sung mô tả CRM hiện hành ngay cả khi thuộc tính không thuộc danh sách từ khóa. Không lấy sản phẩm từ lịch sử cho câu hỏi không rõ mục tiêu ngoài các follow-up đã hỗ trợ.
- Yêu cầu tìm hiểu một sản phẩm đi vào chi tiết; danh sách sản phẩm vẫn đi vào danh mục.
- Các từ chung như gói/suất không được coi là tên sản phẩm để bỏ qua bước hỏi rõ.

Kiểm tra: 132 tests trong answer routing, auto reply channels, RAG components, stability acceptance đạt. Chưa nghiệm thu Facebook thật hoặc toàn bộ loại ngành. Bộ định tuyến còn các bộ xử lý nghiệp vụ riêng; chưa thay toàn bộ bằng bộ phân loại ngữ nghĩa và chưa bảo đảm mọi câu đa ý được trả đủ.
`nBổ sung: sửa câu thuê phòng đó nối với phòng gần nhất trong tin khách, không lấy phòng từ câu bot cũ. Kiểm tra dữ liệu thật hội thoại 5: TRO-P11, giá 2000000, khả dụng 1. Bộ kiểm thử liên quan: 133 đạt; chưa gửi tin Facebook nghiệm thu.
`nLuồng thuê: collection purpose rental_request lưu mục tiêu phòng, hỏi lần lượt tên/số điện thoại/ngày vào, dùng contact storage hiện có và tạo thông báo cho nhân viên khi đủ thông tin. Không tạo đơn hàng, không giữ/trừ phòng; nhân viên xác nhận thủ tục. Test lifecycle và hết khả dụng: 135 ca liên quan đạt. Chưa nghiệm thu Facebook thật.
`nSửa biểu mẫu thuê nhiều trường trong một tin: dùng parser chung, không cho dòng không nhãn ghi đè giá trị có nhãn; từ chối ngày cụ thể đã qua. Gom tin giữ nguyên văn không gọi Gemini viết lại. Giữ cửa sổ 5 giây theo yêu cầu. Đo hai lượt CRM: 5.54s và 6.07s (bao gồm chờ 5s), chưa đo Facebook tới CRM. 154 tests liên quan đạt.
`nĐơn thuê đã nối vào Order/OrderItem nháp bằng helper tạo đơn và giữ tồn hiện có, khóa phiên chống retry trùng, dùng giá CRM tại thời điểm tạo; metadata lưu loại thuê, tên, ngày vào. Giao diện Đơn bán hiển thị ngày vào và SĐT, xác nhận tính cả tồn đang giữ của chính đơn, xử lý expiry UTC. Đã chuyển yêu cầu hoàn tất số 2 thành CHAT-2, chưa xác nhận thay chủ shop. 155 tests đạt gồm tạo/retry/xác nhận/hủy đơn thuê; frontend build đạt. Giữ tồn có hạn theo cơ chế đơn nháp hiện có, chưa có quản lý hợp đồng/thu định kỳ.
`nKiểm tra hội thoại thực: câu hỏi tên bản thân bị RAG trả giá phòng/công tơ; hỏi đã nhận thông tin và thanh toán bị fallback không đúng. Thêm customer_context_reply dùng phiên thu thập/đơn theo tenant+khách+hội thoại trước RAG và trước parser collection. Không tạo thanh toán/cọc từ suy đoán. Replay đọc dữ liệu hội thoại 5: tên chính xác, CHAT-2 nháp, cần xác nhận trước thanh toán. Test bảo đảm không lộ tên sang hội thoại khách khác. 155 tests liên quan đạt. Chưa nghiệm thu tin mới qua Facebook, định tuyến vẫn dựa luật và còn hạn chế câu ngoài các ý đã kiểm tra.
`nLLM collection interpretation: thêm interpreter JSON dùng provider hiện có trong phiên thuê đang mở, nhận nhiều trường, date không nhãn và câu hỏi xen ngang. Prompt chỉ nhận trạng thái/trường đã có và tin hiện tại, không gửi lịch sử toàn bộ hoặc contact lưu. Evidence phải là substring tin khách, tên/phone không được tự sáng tác; xác thực phone/ngày trước lưu. Khi provider lỗi fallback parser cũ. Chưa chuyển toàn bộ định tuyến khởi tạo và checkout bán hàng sang LLM. 160 tests đạt; thử provider thật bằng dữ liệu giả nhận đúng tên/ngày (1.31s), không tạo đơn hoặc gửi Facebook.
