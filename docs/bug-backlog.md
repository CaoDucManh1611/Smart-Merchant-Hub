# Bug backlog – CRM / Smart Merchant Hub

Ngày rà soát: 2026-09-11  
Nhánh: `crm-completion`  
Phạm vi: hai lỗi được phản ánh qua ảnh chụp màn hình và các luồng bán hàng liên quan.

## Tóm tắt ưu tiên

| ID | Mức độ | Khu vực | Trạng thái | Kết luận |
|---|---|---|---|---|
| BUG-001 | P1 | Quyền riêng tư | Đã xác nhận | Bảng đơn hàng đang hiển thị số điện thoại đầy đủ. |
| BUG-002 | P1 | AI/RAG – tra cứu đơn | Đã xác nhận | Câu hỏi về đơn hàng đang rơi xuống fallback RAG chung. |
| BUG-003 | P1 | AI – trả lời trùng | Triệu chứng xác nhận, nguyên nhân cần log thêm | Một tin nhắn hủy đơn nhận cùng một fallback hai lần. Cần khóa/idempotency theo tin nhắn inbound. |
| BUG-004 | P2 | UI bảng đơn | Đã xác nhận | Cột quy trình và thanh toán bị dồn, nút dài bị xuống dòng. |
| BUG-005 | P2 | Hủy đơn | Thiếu luồng nghiệp vụ | Bot chưa có state machine hủy đơn theo trạng thái thực tế. |
| BUG-006 | P1 | Xác thực liên hệ | Thiếu luồng hai bước | Chưa tách kiểm tra định dạng lúc nhận thông tin khỏi OTP trước khi chốt đơn. |

## Bằng chứng từ giao diện

### Ảnh 1 – bảng đơn bán

- Số điện thoại khách hiển thị đầy đủ (`+845...`) trong danh sách đơn.
- Nút `Xem toàn bộ quy trình`, dòng `Nhật ký bất biến` và các nút thanh toán bị ép vào cùng một hàng nên xuống dòng, làm hàng dữ liệu rất cao và khó đọc.
- `bin ×38`, tổng `38.000.000đ` và `0đ / 38.000.000đ` chưa được coi là lỗi dữ liệu: đây có thể là số lượng/giá và trạng thái chưa thanh toán hợp lệ.

### Ảnh 2 – hội thoại bot

- Sau câu `Tôi muốn hủy đơn`, cùng một câu fallback xuất hiện hai lần.
- `Tôi có đơn hàng nào` và `Tôi có đơn hàng nháp nào` nhận fallback kiểu “chưa có thông tin”, dù đây là câu hỏi giao dịch có thể tra từ dữ liệu đơn hàng.
- Bot chưa đưa ra lựa chọn hủy theo trạng thái đơn, cũng chưa chuyển ticket/human takeover một cách có cấu trúc.

## Chi tiết lỗi và hướng sửa

### BUG-001 – Lộ số điện thoại trong danh sách đơn (P1)

**Nguyên nhân đã xác nhận**

- `frontend/src/App.vue` dùng `orderCustomerPhone()` để đưa số điện thoại thô vào cột `SĐT khách`.
- Customer 360 đã có `maskCustomerEmail()` và `maskCustomerPhone()`, nhưng bảng đơn chưa dùng cùng chính sách.

**Đề xuất sửa**

1. Mặc định che số điện thoại/email ở các màn hình danh sách, timeline và preview.
2. Chỉ cho phép xem đầy đủ trong màn hình thao tác đơn khi người dùng có quyền phù hợp; thao tác reveal phải được audit.
3. Dùng một helper privacy thống nhất, tránh mỗi màn hình tự cắt chuỗi khác nhau.

**Tiêu chí nghiệm thu**

- Bảng đơn không hiển thị số điện thoại đầy đủ sau khi reload.
- Tên khách vẫn hiển thị đầy đủ.
- Email/số điện thoại trong Customer 360, timeline và order list có cùng quy tắc che.
- Có test cho dữ liệu thiếu, số ngắn và số quốc tế.

### BUG-002 – Câu hỏi đơn hàng rơi vào fallback RAG (P1)

**Nguyên nhân đã xác nhận**

- `message_service` hiện ưu tiên greeting/customer collection rồi mới gọi `process_rag_auto_reply_background`.
- `prompt_builder` chỉ biết context tài liệu RAG; không phải bộ tra cứu đơn hàng.
- Chưa có route deterministic cho các intent `order_list`, `draft_order_list`, `cancel_order` trước khi gọi RAG.

**Đề xuất sửa**

1. Thêm `transactional_intent_router` chạy trước customer collection/RAG.
2. Nhận diện tối thiểu:
   - “tôi có đơn hàng nào” → đơn gần nhất của khách;
   - “đơn hàng nháp” → các đơn draft còn hiệu lực;
   - “hủy đơn” → kiểm tra trạng thái và chính sách hủy.
3. Query phải lọc theo `tenant/shop` và `customer`, không dùng dữ liệu của khách khác.
4. Chỉ dùng RAG cho chính sách/giải thích; số đơn, trạng thái, giá trị và tồn kho lấy từ database/tool.
5. Nếu không có đơn: trả lời rõ “chưa có đơn” thay vì “chưa có thông tin”.

**Tiêu chí nghiệm thu**

- Ba câu hỏi trên không còn nhận fallback RAG chung.
- Câu trả lời chứa mã đơn, trạng thái, tổng tiền hoặc thông báo không có dữ liệu tương ứng.
- Không lộ đơn của tenant/customer khác.
- Khi database/tool lỗi, bot báo tạm thời không tra được và tạo handoff/ticket phù hợp.

### BUG-003 – Gửi trùng câu trả lời bot (P1)

**Triệu chứng đã xác nhận**

- Một yêu cầu hủy đơn tạo hai tin nhắn outbound có nội dung giống nhau.

**Nguyên nhân cần xác minh thêm**

- Webhook đã có dedupe theo `channel_id + external_event_id`, nhưng background auto-reply chưa có khóa/idempotency rõ ràng theo inbound message.
- Có thể xảy ra khi cùng event đến với provider id khác nhau, khi retry event, hoặc khi nhiều route (collection/escalation/RAG) cùng phát sinh reply.
- `_save_auto_reply_outbound` chỉ chống trùng theo outbound provider `message_id`; không chặn hai lần gọi send trước khi có hai message id khác nhau.

**Đề xuất sửa**

1. Gắn `auto_reply_key = conversation_id + inbound_message_id` cho mỗi lượt xử lý.
2. Tạo guard có unique constraint/transaction lock trước khi gửi outbound.
3. Lưu route đã thắng (`collection`, `greeting`, `transactional`, `escalation`, `rag`) để các route khác bỏ qua.
4. Ghi correlation id vào inbound, outbound, timeline và log provider.
5. Với retry hợp lệ, chỉ retry khi lượt trước chưa gửi thành công; không gửi lại khi đã có outbound thành công.

**Tiêu chí nghiệm thu**

- Gửi lại cùng webhook hoặc xử lý song song vẫn chỉ có một tin bot.
- Timeline chỉ có một event outbound tương ứng.
- Có log để truy ngược `inbound_message_id → route → outbound_message_id`.
- Test race/concurrent không tạo hai phản hồi.

> Chưa nên “chữa” bằng cách lọc hai tin có cùng nội dung ở UI. Cách đó che triệu chứng nhưng vẫn có thể gửi trùng ra Telegram/Zalo/Instagram.

### BUG-004 – Bảng đơn bị dồn và xuống dòng (P2)

**Nguyên nhân đã xác nhận**

- Bảng có nhiều cột với `min-width: 1280px`.
- Nhãn nút dài và payment controls nằm chung một cell.
- Một số style cho phép nội dung hành động wrap tự do.

**Đề xuất sửa**

1. Giữ bảng có scroll ngang ở màn hình hẹp, không ép co toàn bộ cột.
2. Rút gọn nhãn thành `Quy trình`, `Lịch sử`, `Thu`, `Hoàn`; tooltip hiển thị mô tả đầy đủ.
3. Đặt `white-space: nowrap` cho nút/trạng thái và min-width riêng cho các cột quan trọng.
4. Gom các nút thanh toán vào menu hoặc nhóm compact; giữ tổng tiền và trạng thái dễ quét.
5. Kiểm tra ở độ rộng 1440, 1280, 1024 và mobile.

**Tiêu chí nghiệm thu**

- Không còn nút bị cắt hoặc xuống ba dòng.
- Hàng đơn giữ chiều cao ổn định.
- Các thao tác vẫn có keyboard focus và tooltip/accessibility label.
- Không làm mất khả năng xem chi tiết trên màn hình hẹp.

### BUG-005 – Hủy đơn chưa có luồng nghiệp vụ (P2)

**Khoảng trống hiện tại**

- Bot mới trả lời chung khi gặp “hủy đơn”; chưa kiểm tra trạng thái `draft/confirmed/packing/shipping/completed`.

**Đề xuất sửa**

| Trạng thái | Hành vi đề xuất |
|---|---|
| `draft` | Cho phép hủy sau khi khách xác nhận lại. |
| `confirmed` | Tạo yêu cầu hủy, khóa xử lý tự động và báo nhân viên xác nhận. |
| `packing`/`shipping` | Không tự hủy; tạo ticket ưu tiên cao và hướng dẫn liên hệ. |
| `completed` | Chuyển sang quy trình đổi trả/khiếu nại, không gọi là hủy đơn. |
| Không tìm thấy | Nói rõ chưa có đơn phù hợp, không dùng fallback RAG. |

**Tiêu chí nghiệm thu**

- Không chuyển trạng thái trái phép.
- Mọi yêu cầu hủy có audit/timeline.
- Handoff được bật khi cần người thật.
- Bot không hỏi lại thông tin đã có trong customer/order context.

### BUG-006 – Xác thực email/số điện thoại theo hai bước (P1)

**Luồng cần bổ sung**

Tách rõ “kiểm tra dữ liệu” và “xác thực quyền sở hữu thông tin”:

1. **Ngay khi nhận thông tin khách hàng**
   - Kiểm tra định dạng số điện thoại/email.
   - Chuẩn hóa số điện thoại về một định dạng thống nhất và trim email.
   - Báo lỗi ngay nếu sai định dạng, không tạo dữ liệu bẩn.
   - Không gửi OTP ở bước này để tránh làm phiền khi khách chưa quyết định mua.

2. **Sau khi tạo đơn nháp, trước khi khách xác nhận**
   - Tạo đơn nháp với trạng thái `contact_verification_pending`.
   - Gửi OTP xác thực số điện thoại; email chỉ gửi OTP khi khách cung cấp email hoặc shop bật chính sách bắt buộc.
   - Chỉ cho phép chuyển đơn nháp sang xác nhận/chính thức khi thông tin bắt buộc đã ở trạng thái `verified`.
   - Nếu OTP hết hạn/vượt số lần thử, giữ đơn nháp, cho phép gửi lại có giới hạn hoặc chuyển nhân viên hỗ trợ.

**Quy tắc nghiệp vụ**

- Số điện thoại là thông tin bắt buộc để chốt đơn COD.
- Email không bắt buộc với COD nếu shop không yêu cầu; nếu đã cung cấp thì phải xác thực trước khi gửi hóa đơn/thông báo qua email.
- Đơn nháp không trừ tồn kho chính thức và chưa tính doanh thu.
- Không lưu OTP dạng thô; OTP phải có thời hạn, giới hạn thử lại, cooldown gửi lại và audit event.
- Customer 360 chỉ hiển thị trạng thái `Chưa xác thực`, `Đang chờ OTP` hoặc `Đã xác thực`; dữ liệu hiển thị vẫn phải được che theo chính sách privacy.

**Tiêu chí nghiệm thu**

- Sai định dạng được báo ngay khi khách nhập/cung cấp thông tin.
- Tạo đơn nháp không tự động coi số điện thoại/email là đã xác thực.
- OTP được gửi sau khi có draft và trước bước xác nhận cuối.
- Không thể tạo đơn chính thức khi số điện thoại bắt buộc chưa `verified`.
- Retry OTP không tạo thêm đơn nháp hoặc outbound bot trùng.
- Hết hạn OTP không làm mất đơn nháp; nhân viên có thể tiếp quản và audit được toàn bộ thao tác.

## Những điểm chưa kết luận là bug

- `0đ / 38.000.000đ` là biểu diễn hợp lý cho đơn chưa thanh toán.
- `bin ×38` và tổng tiền chỉ là lỗi nếu sai với giá/số lượng trong database; cần đối chiếu dữ liệu trước khi sửa.
- Trạng thái `confirmed` không tự động có nghĩa là đơn đã giao hoặc đã thanh toán.

## Thứ tự xử lý đề xuất

1. **BUG-001 và BUG-002**: chặn lộ dữ liệu và sửa route giao dịch; viết test trước khi đổi hành vi.
2. **BUG-003**: thêm correlation/idempotency, sau đó tái hiện bằng webhook trùng và xử lý song song.
3. **BUG-006**: thêm validation lúc nhận thông tin và OTP sau draft, trước xác nhận.
4. **BUG-005**: hoàn thiện state machine hủy đơn dựa trên trạng thái thật.
5. **BUG-004**: chỉnh layout sau khi cấu trúc dữ liệu/hành động ổn định.
6. Chạy regression toàn bộ backend/frontend và test thủ công trên Telegram, Zalo, Instagram.

## Ma trận kiểm thử bắt buộc

| Nhóm | Kịch bản | Kết quả mong đợi |
|---|---|---|
| Tra cứu | `Tôi có đơn hàng nào` | Trả danh sách đơn gần nhất hoặc nói rõ không có đơn. |
| Tra cứu | `Tôi có đơn hàng nháp nào` | Trả đúng các đơn draft của khách hiện tại. |
| Hủy | `Tôi muốn hủy đơn` với draft | Xác nhận rồi hủy đúng draft. |
| Hủy | Hủy đơn đang giao | Tạo ticket/handoff, không tự đổi trạng thái. |
| Liên hệ | Khách nhập số điện thoại/email sai định dạng | Báo lỗi ngay, không tạo thông tin bẩn. |
| Liên hệ | Tạo draft với thông tin hợp lệ | Trạng thái xác thực là `pending`, chưa phải `verified`. |
| Liên hệ | OTP đúng sau khi tạo draft | Đánh dấu số điện thoại/email đã xác thực, cho phép khách xác nhận. |
| Liên hệ | OTP sai/hết hạn | Không chốt đơn; giữ draft, giới hạn retry hoặc handoff. |
| Lặp | Gửi cùng webhook hai lần | Một outbound, một timeline event. |
| RAG | Hỏi chính sách đổi trả | Dùng RAG, không bịa trạng thái đơn. |
| Riêng tư | Mở order list/Customer 360 | Tên rõ; email và điện thoại được che. |
| UI | 1440/1280/1024/mobile | Không vỡ layout, nút không bị cắt. |

## Ghi chú triển khai an toàn

- Không xóa dữ liệu đơn cũ để “hết lỗi” nếu chưa có migration/backup.
- Hủy đơn chỉ là chuyển trạng thái hợp lệ; không hard-delete.
- Xác thực liên hệ không được làm lộ OTP trong log; chỉ lưu hash/trạng thái/thời điểm và số lần thử.
- Mọi thay đổi liên quan customer/order/bot mode phải giữ audit trail.
- Trước khi sửa BUG-003 cần bật log correlation ở môi trường dev/staging để xác nhận nhánh gây trùng.
