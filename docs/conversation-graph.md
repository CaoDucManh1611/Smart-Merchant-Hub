# Điều phối hội thoại LangGraph

## Luồng đang tích hợp

Tin nhắn -> job gom tin 5 giây -> kiểm tra bot/quyền riêng tư -> LangGraph:
1. Plan: LLM chọn answer / workflow / handoff và tối đa 3 công cụ đọc.
2. Tools: catalog CRM hiện hành, hồ sơ chính khách, đơn chính khách, truy xuất tri thức.
3. Compose: LLM trả JSON câu trả lời + số nguồn. Kiểm tra citation/số tiền/mã/nguồn trước gửi.
4. Workflow chuyển sang service collection/order hiện có, gồm interpreter LLM cho phiên thuê. Handoff gọi service chuyển nhân viên hiện có, không tự tắt bot.

Không cấp SQL, filesystem hoặc HTTP tùy ý cho model. Tenant/customer/conversation lấy từ server, không nhận từ output model. Mỗi lượt tối đa 2 model calls trong nhánh trả lời, không có vòng agent vô hạn. Tin mới đến trong lúc sinh câu trả lời làm lượt cũ dừng trước gửi.

## Lưu trạng thái và retry

Không thêm checkpoint store thứ hai. Trạng thái nghiệp vụ ở collection/order; câu trả lời đã sinh ở payload collection_reply của CrmJob trước gửi. Graph đọc lại trạng thái DB theo từng lượt. LangGraph ở đây điều phối một lượt, chưa phải durable graph checkpoint hoặc interrupt/resume tự động cho toàn bộ nghiệp vụ. Mã phiên bản backend/worker được kiểm tra sau khởi động.

Cờ CHATBOT_GRAPH_ENABLED mặc định true; false quay lại cơ chế trước. Lỗi planner/provider/schema trong luồng mới trả lỗi rõ ràng, không âm thầm phát sinh thao tác. Quota AI được ghi cho plan và compose.

## Giới hạn được biết

- Khởi tạo/đổi/hủy đơn còn đi qua service nghiệp vụ và các luật cũ; chưa chuyển toàn bộ sang tool calling tự do.
- Catalog tối đa 100 bản ghi, đơn tối đa 5 bản gần nhất. Cần công cụ tìm kiếm/phân trang cho shop lớn.
- RAG vẫn dùng retriever hiện tại; chưa sửa toàn bộ parent expansion.
- Kiểm tra citation hiện có không chứng minh mọi mệnh đề ngữ nghĩa đều đúng.
- Có thêm latency/cost cho lập kế hoạch; chưa có benchmark tải đồng thời.
- Tích hợp thêm dependency langgraph==1.2.16 trong requirements; khi dựng container mới cần build/install requirements, không dùng image cũ thiếu dependency.

## Kiểm chứng

165 tests liên quan đạt: graph allowlist, giới hạn tool, workflow không gọi tool đọc, nguồn sai bị chặn, handoff, collection, routing, channels, RAG components/stability. Thử model thật trên dữ liệu shop, không gửi Facebook: tên + trạng thái đơn tra đúng CRM; hỏi Wi-Fi trả thiếu dữ liệu. Chưa nghiệm thu live Facebook hoặc toàn bộ chuỗi kinh doanh/đa ngành.

Tham khảo: https://docs.langchain.com/oss/python/langgraph/graph-api ; https://www.chatwoot.com/hc/user-guide/articles/1777328078-lesson-5-ai-actions
