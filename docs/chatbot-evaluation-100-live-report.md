# Báo cáo kiểm thử chatbot 100 câu

Ngày chạy: 12/10/2026  
Bộ câu hỏi: `docs/chatbot-evaluation-set.jsonl`  
Phạm vi: trợ lý hỏi đáp nội bộ của shop demo; không gửi tin cho khách thật.

## Kết quả thực thi

Đã gửi đủ 100 câu khác nhau và đối chiếu đủ 100 mã câu hỏi với nhật ký máy chủ. Có thêm 2 lượt chạy trùng trong quá trình kiểm tra.

| Trạng thái | Số lượt | Diễn giải |
|---|---:|---|
| Trả lời từ CRM | 46 | Dữ liệu sản phẩm/đơn hàng có thể được xử lý không cần mô hình sinh câu trả lời. |
| Trả lời RAG thành công | 7 | Mô hình trả lời sau khi lấy tài liệu. |
| Không có câu trả lời đủ tin cậy | 15 | Gồm thiếu dữ liệu hoặc bị cổng trích dẫn từ chối. |
| Chuyển nhân viên | 9 | Hành vi an toàn với yêu cầu cần người thật hoặc dữ liệu nhạy cảm. |
| Lỗi dịch vụ mô hình | 23 | 11 `RateLimitError`, 12 `ApiKeyPoolUnavailable`; không phải lỗi truy xuất tài liệu. |

Đây là thống kê trạng thái chạy, không phải “77/100 câu đúng”. Các câu được gửi tuần tự trong cùng một hội thoại, nên lịch sử của câu trước có thể ảnh hưởng câu sau; bộ này chưa phải phép đo độc lập cho từng câu.

Kiểm tra định tuyến ngoại tuyến riêng đạt 100/100, nhưng chỉ xác nhận bộ phân loại chọn đúng nhánh dự kiến; nó không xác nhận nội dung câu trả lời, nguồn trích dẫn hay dữ liệu CRM thực tế.

## Lỗi đã xác nhận và thay đổi

1. Câu “Chiếc váy này giá bao nhiêu vậy?” từng bị gắn với sản phẩm điện gia dụng được hỏi trước đó. Đã chặn kế thừa sản phẩm cũ khi câu mới nêu một loại hàng khác. Hành vi mong đợi là hỏi khách tên hoặc mã sản phẩm; câu nối tiếp “Còn hàng không?” vẫn được phép kế thừa sản phẩm vừa được xác định.
2. Câu “Sản phẩm nào bán chạy nhất tháng này?” từng nhận danh sách toàn bộ sản phẩm. Đã chuyển nhánh này sang thống kê số lượng trong đơn hoàn tất của đúng shop, trong tháng hiện tại; đơn hủy, hoàn tiền, lỗi thanh toán và dữ liệu shop khác bị loại. Nếu không có dữ liệu bán hàng, bot báo chưa đủ dữ liệu và yêu cầu nhân viên kiểm tra, không tự xếp hạng.

## Kiểm thử mã sau thay đổi

- `python scripts/evaluate_rag_set.py` — 100/100 định tuyến.
- `python -m pytest -q backend/tests/test_chatbot_answer_routing.py backend/tests/test_rag_crm_model_integration.py` — 43 kiểm thử qua.
- Các kiểm thử mới bao phủ không trộn sản phẩm cũ vào câu hỏi loại hàng mới, chỉ xếp hạng từ đơn đủ điều kiện trong shop hiện tại, và không bịa thứ hạng khi chưa có đơn.

## Lộ trình ưu tiên

1. **Độ tin cậy dịch vụ AI:** xử lý 23 lỗi giới hạn/quota bằng theo dõi quota, giới hạn tốc độ và dự phòng nhà cung cấp; giữ câu trả lời an toàn khi mọi nhà cung cấp đều lỗi. Không tự gửi lặp lại tin nhắn khách.
2. **Đo đúng chất lượng trả lời:** chạy mỗi câu trong ngữ cảnh sạch hoặc fixture hội thoại riêng; chấm riêng định tuyến, câu trả lời bắt buộc/cấm, độ chính xác nguồn và trích dẫn. Không tính câu chuyển nhân viên an toàn là lỗi.
3. **Củng cố dữ liệu shop:** bổ sung chính sách giao hàng, thanh toán, đổi trả/bảo hành đã được shop duyệt; dữ liệu đơn, tồn kho và doanh số lấy từ CRM theo đúng shop, không đưa số liệu thay đổi theo thời gian vào tài liệu tĩnh.
4. **RFM và gợi ý sản phẩm:** chỉ tính trên đơn hoàn tất đã khấu trừ hoàn tiền; so sánh mô hình với luật cơ sở trên dữ liệu giả lập/được shop cho phép, đo hit-rate và độ bao phủ trước khi bật cho khách thật.
5. **An toàn phát hành:** giữ bộ 100 câu làm kiểm tra hồi quy và chạy tự động trước mỗi lần cập nhật; theo dõi riêng từng shop, tỷ lệ không có nguồn, trích dẫn sai, chuyển nhân viên và lỗi nhà cung cấp.

## Trạng thái áp dụng trên giao diện đang mở

Các thay đổi đã qua kiểm thử mã. Docker backend hiện chạy tiến trình không tự nạp lại mã Python; lần kiểm tra giao diện sau thay đổi vẫn trả kết quả từ tiến trình cũ. Vì lúc khởi động backend còn chạy các bước nâng cấp cơ sở dữ liệu, chưa tự khởi động lại dịch vụ trong lượt này. Cần khởi động lại backend theo quy trình Docker của dự án rồi kiểm tra lại hai câu tái hiện ở trên trước khi coi thay đổi đã có hiệu lực trên giao diện.
