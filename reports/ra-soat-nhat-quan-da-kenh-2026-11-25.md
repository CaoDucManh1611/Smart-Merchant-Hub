# Rà soát tính nhất quán chatbot đa kênh

Ngày: 25/11/2026. Source: C:/Users/DUC_STRONG/Projects/Smart-Merchant-Hub.
Phạm vi: đọc source đường nhận tin, xử lý lượt chat, gửi phản hồi và log worker. Không gửi tin thử trên tài khoản khách; không thay source trong lần rà soát này. Không phải chứng nhận mọi kênh hoạt động.

## Kết luận
Các kênh có lõi xử lý chung, nhưng không thể suy từ Zalo của một khách chạy được rằng khách mới và mọi kênh đều chạy được. Cần kiểm tra cả shop/channel được gán, trạng thái riêng của hội thoại, API AI và giao nhận connector. Chưa có bằng chứng xác định nguyên nhân cuộc chat của người bạn vì chưa đối chiếu lượt tin cụ thể.

## Đường đi đã đọc
- Telegram/Zalo/Facebook: API tương ứng gọi process_and_save_message (backend/app/api/telegram.py:17, zalo.py:22, facebook.py:20).
- message_service.py:2019–2021 đưa tin vào schedule_chatbot_turn; conversation_turn_service.py:156 gọi graph_reply.
- Local connector có đường nhập và chuẩn hóa riêng. local_connectors.py:995 đưa tin live trùng với lịch sử vào hàng đợi lại, dùng khóa công việc ổn định chống trả lời hai lần.
- auto_reply_service.py:837 (_send_channel_reply) phân nhánh gửi theo kênh: Meta qua send_meta_text/image, Telegram và Zalo qua service riêng, TikTok/Shopee qua hàm gửi riêng. Vì vậy cùng nội dung AI không đồng nghĩa cùng mức ổn định giao tin.

## Điểm cần xử lý/kiểm chứng theo ưu tiên

### P1 — Trạng thái hội thoại làm khách mới và khách cũ đi khác nhánh
Đã xác nhận trong phiên trước: conversation 24/shop 7 có business_request pending ở payment_method, chặn mua sản phẩm. Đã sửa chuyển bản nháp khi khách chọn rõ sản phẩm. Cần hồi quy cả chiều sản phẩm sang dịch vụ, hủy, yêu cầu hoàn và đơn đã hoàn thành; không được áp bản nháp khách này sang khách khác. Đừng xóa toàn bộ lịch sử để chữa lỗi.
Vị trí: customer_collection_flow.py (_get_session/advance_customer_collection); conversation_graph.py (existing_checkout/business_session).

### P1 — Không phản hồi có thể là điều kiện dừng chủ động
conversation_turn_service.py:57 dừng khi bot_mode=human; dòng 140 dừng khi shop tắt auto reply. Dòng 84 bỏ lượt trước nếu có tin inbound mới hơn để gom lượt. Các nhánh return False cần có lý do được ghi rõ để phân biệt tắt bot, chờ gom tin và lỗi. Hiện việc chẩn đoán chỉ từ giao diện rất khó. Đây là rủi ro quan sát vận hành, không phải bằng chứng các điều kiện đó đang sai.

### P1 — Đường nhập lịch sử khác tin live
message_service.py có history_import; local_connectors.py có is_live và xử lý trùng. Nếu watcher/connector đánh dấu sai, tin khách có thể được lưu mà không trở thành lượt hỏi bot đúng thời điểm. Cần kiểm tra Facebook/Instagram với cuộc chat mới, tin chưa mở, mất kết nối rồi kết nối lại và nhập lịch sử. Chưa xác nhận lỗi hiện hành trong các trường hợp này.

### P1 — API AI vẫn là điểm lỗi chung
Log đã thấy RateLimitError/ProviderCircuitOpen dẫn tới graph_unavailable. Key mới gọi thử thành công không bảo đảm quota cả ngày. Nhánh dự phòng vừa thêm chỉ bao phủ một số lỗi provider và ý định mua; câu tư vấn khác vẫn có thể rơi vào phản hồi chung. Cần kiểm tra chuyển provider và bảo toàn phiên giao dịch; không nên kết luận lỗi do khách mới chỉ từ câu dự phòng.

### P1 — Gửi ra nền tảng là bước độc lập
Auto reply có trạng thái sending/sent/delivery_unknown/failed; delivery_unknown được chặn gửi lại tùy tiện để tránh trùng. Cần đối chiếu mã tin và bằng chứng xuất hiện ở nền tảng đích, đặc biệt connector UI Facebook/Instagram/TikTok/Shopee. Không được coi chỉ có bong bóng trong SMH là bằng chứng khách đã nhận.

### P2 — Gom nhiều tin tạo đầu vào khác nhau
conversation_turn_service.py gom tối đa 12 mảnh trong khoảng chờ và bỏ lượt cũ khi có inbound mới. Khách gửi cùng câu nhưng tốc độ hoặc cách tách tin khác nhau có thể tạo query khác. Cần thử form một tin và nhiều tin, cả trường hợp contact card/ảnh xen giữa.

### P2 — Nhận diện cách diễn đạt chưa đồng đều
Đã thấy “thông tin” và “thông tin chi tiết” đi khác nhánh; vừa bổ sung nhánh thông tin sản phẩm. Cần kiểm tra cả câu đầy đủ không có lịch sử và câu tham chiếu cần lịch sử. Khi thiếu ngữ cảnh phải hỏi làm rõ, không tự lấy sản phẩm cũ không liên quan.

## Đánh giá theo kênh
| Kênh | Có đường xử lý/gửi trong source | Bằng chứng hiện có | Kết luận |
|---|---|---|---|
| Zalo | Có | Log shop 7/conversation 24 có các lượt catalog_detail, pending, partial, completed và delivery_state=sent; người dùng quan sát hoạt động | Có hoạt động ở cuộc chat đã thử, chưa đủ xác nhận khách mới |
| Telegram | Có service nhận/gửi và QR | Chưa thử trực tiếp trong lần rà soát | Chưa xác nhận |
| Facebook/Instagram | Có đường Meta và connector nhập live/lịch sử | Chưa thử trực tiếp trong lần rà soát | Chưa xác nhận; ưu tiên kiểm tra connector |
| TikTok/Shopee | Có nhánh gửi riêng, có xử lý QR | Chưa thử trực tiếp; có source không đồng nghĩa connector đang bật | Chưa xác nhận; Shopee từng được yêu cầu dừng, không tự bật lại |

## Ma trận kiểm tra cần chạy trước demo
Mỗi kênh đang bật: dùng khách mới và khách có lịch sử, cùng shop, cùng quyền bot. Thử (1) chào, (2) tất cả sản phẩm, (3) nhóm serum/toner, (4) thông tin một mã hàng, (5) mua số lượng rõ, (6) form tách nhiều tin, (7) hủy bản nháp, (8) hỏi dịch vụ sau khi mua, (9) QR, (10) khách nhận thông báo trạng thái đơn. Khách mới hỏi “cái đó” phải được hỏi lại. Các câu đầy đủ phải lấy cùng danh mục/giá; thông tin cá nhân và đơn chỉ thuộc đúng khách. Chỉ tạo đơn thử khi được phép và không ghi thanh toán thật.

Mỗi ca ghi: business_id, channel_id, conversation_id, source message ID, query đã gom, intent/status, mã lỗi provider, trạng thái gửi và mã tin đầu ra. Không ghi API key hoặc toàn bộ thông tin cá nhân vào báo cáo.

## Thứ tự đề xuất
1. Bổ sung lý do dừng và theo dõi toàn chuỗi nhận–xử lý–gửi.
2. Hồi quy phiên mới/phiên cũ và chuyển sản phẩm–dịch vụ trong lõi chung.
3. Kiểm tra khách mới ở Zalo, sau đó Telegram, Facebook/Instagram, rồi các connector đang bật.
4. Chỉ sửa từng lỗi đã tái hiện, lưu mốc khôi phục trước thay đổi lớn; không viết lại toàn bộ connector cùng lúc.
