# Bug backlog – CRM / Smart Merchant Hub

Ngày rà soát: 2026-09-12
Nhánh: `crm-completion`  
Phạm vi: các lỗi được phản ánh qua ảnh chụp màn hình, luồng bán hàng, RAG và Customer 360.

## Tóm tắt ưu tiên

| ID | Mức độ | Khu vực | Trạng thái | Kết luận |
|---|---|---|---|---|
| BUG-001 | P1 | Quyền riêng tư | Đã sửa – test xanh | Bảng đơn hàng đã dùng masking thống nhất cho số điện thoại/email. |
| BUG-002 | P1 | AI/RAG – tra cứu đơn | Đã sửa – test xanh | Router giao dịch chạy trước collection/RAG, truy vấn theo tenant/customer. |
| BUG-003 | P1 | AI – trả lời trùng | Đã sửa – test xanh | Inbound dedupe và khóa `auto_reply_key` theo route đã được bật. |
| BUG-004 | P2 | UI bảng đơn | Đã sửa – test xanh | Bảng có scroll ngang, nút compact/tooltip và controls không wrap. |
| BUG-005 | P2 | Hủy đơn | Đã sửa – test xanh | Hủy/hoàn đơn kiểm tra trạng thái, giải phóng tồn và handoff khi cần. |
| BUG-006 | P1 | Xác thực liên hệ | Đã sửa – test xanh | Contact được chuẩn hóa, validate, dedupe và giữ trạng thái xác minh. |
| BUG-007 | P1 | AI/RAG – sản phẩm cụ thể | Đã sửa – test xanh | Tên/SKU/alias cụ thể được resolve thành quote riêng, không trả catalog. |
| BUG-008 | P1 | Hủy/tra cứu đơn | Đã sửa – test xanh | Hủy theo mã/món/kênh có danh sách lựa chọn và thông báo trạng thái thân thiện. |
| BUG-011 | P1 | Unified Timeline | Đã sửa – test xanh | Actor bot/staff/system/customer và correlation id được giữ nhất quán. |
| BUG-012 | P2 | Inbox/UI | Đã sửa – test xanh | Empty state và responsive grid lấp đầy panel, không còn khoảng trống vô nghĩa. |
| BUG-013 | P1 | RAG/combo | Đã sửa – test xanh | Giá món lẻ, giá combo, chênh lệch và thành phần lấy từ catalog hiện tại. |
| BUG-014 | P1 | Gợi ý sản phẩm | Đã sửa – test xanh | Route cụ thể ưu tiên quote/card; route catalog không còn gửi lặp. |
| BUG-015 | P2 | Customer 360/UI | Đã sửa – test xanh | Card chỉ hiển thị bản chính; lịch sử gom trong “Xem thêm” và vẫn được che dữ liệu. |

## Kết quả triển khai và kiểm thử

- Backend: `398 passed` với cấu hình provider ngoài được tắt trong môi trường local.
- Frontend: `96/96` test shell và build production thành công.
- Đã bổ sung regression cho router giao dịch, hủy/hoàn theo mã–món–kênh, quote sản phẩm cụ thể, giá món lẻ trong combo, contact/address dedupe, OTP và Customer 360 overflow.
- Các bước cần chạy ở staging trước release vẫn phụ thuộc hạ tầng/secret thật: migration + restore PostgreSQL, ký webhook Telegram/Zalo/Facebook/Instagram, Redis/proxy rate limit, secret manager và nhà cung cấp OTP. Runbook/script tương ứng đã có; không thể giả lập việc cấp quyền hoặc gửi OTP thật trong local.

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

### BUG-006 – Kiểm tra và chuẩn hóa thông tin liên hệ (P1)

**Luồng cần bổ sung**

1. Khi khách nhập số điện thoại/email, kiểm tra định dạng ngay lập tức.
2. Chuẩn hóa số điện thoại và trim email trước khi lưu.
3. Không tạo thêm bản ghi contact nếu cùng loại và cùng giá trị đã tồn tại.
4. Nếu dữ liệu sai, hỏi lại đúng trường đang thiếu thay vì chuyển sang bước kế tiếp.
5. Customer 360 hiển thị trạng thái contact rõ ràng nhưng không lộ dữ liệu đầy đủ.

**Phạm vi hiện tại**

- Email OTP tạm thời không nằm trong backlog xử lý này.
- Đơn nháp và lịch sử đơn vẫn phải giữ nguyên; chỉ sửa validation và cách hiển thị.

**Tiêu chí nghiệm thu**

- Sai định dạng được báo ngay khi khách nhập/cung cấp thông tin.
- Nhập cùng email/số điện thoại ở nhiều đơn không tạo contact trùng.
- Không mất dữ liệu lịch sử và không lộ thông tin nhạy cảm.

## Những điểm chưa kết luận là bug

- `0đ / 38.000.000đ` là biểu diễn hợp lý cho đơn chưa thanh toán.
- `bin ×38` và tổng tiền chỉ là lỗi nếu sai với giá/số lượng trong database; cần đối chiếu dữ liệu trước khi sửa.
- Trạng thái `confirmed` không tự động có nghĩa là đơn đã giao hoặc đã thanh toán.

## Thứ tự xử lý đề xuất

1. **BUG-001, BUG-011**: chặn lộ dữ liệu và sửa actor labeling trong Customer 360/Unified Timeline.
2. **BUG-002, BUG-007, BUG-013, BUG-014**: sửa transactional/product router trước RAG, rồi kiểm thử resolver tên/SKU/alias và giá live.
3. **BUG-003**: thêm correlation/idempotency, sau đó tái hiện bằng webhook trùng và xử lý song song.
4. **BUG-006**: hoàn thiện kiểm tra định dạng và trạng thái thông tin liên hệ; email OTP tạm thời không nằm trong phạm vi.
5. **BUG-005, BUG-008**: hoàn thiện state machine hủy đơn, chọn đơn theo mã/món/kênh và thông báo trạng thái dễ hiểu.
6. **BUG-004, BUG-012, BUG-015**: chỉnh layout bảng/inbox/Customer 360 sau khi cấu trúc dữ liệu và route đã ổn định.
7. Chạy regression toàn bộ backend/frontend và test thủ công trên Telegram, Zalo, Instagram.

## Ma trận kiểm thử bắt buộc

| Nhóm | Kịch bản | Kết quả mong đợi |
|---|---|---|
| Tra cứu | `Tôi có đơn hàng nào` | Trả danh sách đơn gần nhất hoặc nói rõ không có đơn. |
| Tra cứu | `Tôi có đơn hàng nháp nào` | Trả đúng các đơn draft của khách hiện tại. |
| Hủy | `Tôi muốn hủy đơn` với draft | Xác nhận rồi hủy đúng draft. |
| Hủy | `Tôi muốn hủy đơn` khi có nhiều đơn | Liệt kê mã, kênh, món, số lượng, tổng tiền và trạng thái để khách chọn. |
| Hủy | `Hủy đơn Combo chăm sóc da cơ bản` | Resolve theo tên món và hủy đúng đơn thuộc customer hiện tại. |
| Hủy | `Hủy đơn Telegram` | Lọc theo kênh, không hỏi mã đơn một cách mù quáng. |
| Hủy | Hủy đơn đang giao | Tạo ticket/handoff, không tự đổi trạng thái. |
| Liên hệ | Khách nhập số điện thoại/email sai định dạng | Báo lỗi ngay, không tạo thông tin bẩn. |
| Liên hệ | Nhập email/số điện thoại sai định dạng | Báo lỗi ngay, không tạo contact trùng hoặc dữ liệu bẩn. |
| Liên hệ | Nhập lại contact ở nhiều đơn | Dùng lại contact đã có, không nhân bản dòng trong Customer 360. |
| Lặp | Gửi cùng webhook hai lần | Một outbound, một timeline event. |
| Sản phẩm | `Tôi muốn mua 3 sản phẩm Kem chống nắng Daily Shield` | Trả quote riêng đúng món, giá, tồn và tổng tiền; không trả toàn catalog. |
| Sản phẩm | Hỏi món lẻ trong combo | Trả giá lẻ, giá combo và chênh lệch chính xác. |
| RAG | Hỏi chính sách đổi trả | Dùng RAG, không bịa trạng thái đơn. |
| Timeline | Tin bot/hệ thống/nhân viên | Hiển thị đúng actor, không gắn nhầm thành Khách hàng. |
| Customer 360 | Nhiều contact/địa chỉ trùng | Card chỉ hiển thị bản chính; phần còn lại nằm trong “Xem thêm”. |
| Riêng tư | Mở order list/Customer 360 | Tên rõ; email và điện thoại được che. |
| UI | 1440/1280/1024/mobile | Không vỡ layout, nút không bị cắt. |

## Ghi chú triển khai an toàn

- Không xóa dữ liệu đơn cũ để “hết lỗi” nếu chưa có migration/backup.
- Hủy đơn chỉ là chuyển trạng thái hợp lệ; không hard-delete.
- Thông tin liên hệ không được lộ trong log; chỉ lưu giá trị đã che/hash và trạng thái thay đổi cần thiết.
- Mọi thay đổi liên quan customer/order/bot mode phải giữ audit trail.
- Trước khi sửa BUG-003 cần bật log correlation ở môi trường dev/staging để xác nhận nhánh gây trùng.

### BUG-007 – Khách nêu sản phẩm cụ thể nhưng bot trả toàn bộ catalog (P1)

**Bằng chứng**

- Khách nhắn dạng `tôi muốn mua 3 sản phẩm Kem chống nắng Daily Shield`.
- Bot lại trả danh sách `bin`, combo, serum, kem chống nắng… thay vì báo đúng món, số lượng, giá và tồn kho.

**Nguyên nhân cần sửa**

- Bộ nhận diện `is_browsing_request` bắt cụm “muốn mua sản phẩm” trước khi resolver kiểm tra tên sản phẩm thực tế.
- Vì vậy câu mua hàng có tên sản phẩm bị route sang catalog fallback.

**Hành vi đúng**

1. Resolve tên/SKU sản phẩm trước khi kết luận đây là câu hỏi catalog.
2. Nếu có tên sản phẩm + động từ mua/đặt/lấy/chốt và số lượng, trả quote riêng cho sản phẩm đó.
3. Quote phải có tên, SKU, số lượng, giá một đơn vị, tổng tiền, tồn khả dụng và bước xác nhận.
4. Chỉ trả toàn bộ catalog cho câu hỏi chung như “shop có sản phẩm gì?”.

**Tiêu chí nghiệm thu**

- Không còn lặp danh sách catalog với yêu cầu có sản phẩm cụ thể.
- `3 Kem chống nắng Daily Shield` trả đúng tổng tiền và tồn kho.
- Tên gần đúng/SKU/alias vẫn resolve được; không resolve được thì hỏi lại tên sản phẩm, không bịa giá.

### BUG-008 – Hủy đơn theo tên món/kênh và lỗi `order_already_closed` (P1)

**Bằng chứng**

- `Tôi muốn hủy cái đơn Combo chăm sóc da cơ bản` không được dùng tên món để chọn đơn.
- `Tôi muốn hủy đơn Telegram` bị coi là nhiều đơn và chỉ yêu cầu mã đơn, không hiển thị danh sách có sản phẩm/kênh.
- Với đơn đã hủy/đã hoàn, bot trả nguyên mã nội bộ `order_already_closed`.

**Hành vi đúng**

1. Khi khách nói hủy mà chưa có mã đơn, liệt kê các đơn thuộc đúng customer, gồm: mã đơn, kênh, sản phẩm, số lượng, tổng tiền, trạng thái.
2. Cho khách nhập mã đơn, tên món hoặc kênh để chọn; nếu còn nhiều kết quả thì thu hẹp tiếp, không tự chọn sai đơn.
3. `draft`/`confirmed`: hủy đúng đơn và giải phóng tồn giữ nếu có.
4. `processing`/`shipped`: không tự đổi trạng thái nếu chính sách không cho phép; tạo ticket/handoff.
5. `cancelled`: nói rõ “đơn đã được hủy trước đó”; `refunded`: nói rõ “đơn đã hoàn tiền”; không lộ mã lỗi kỹ thuật.
6. Ghi audit/timeline cho cả yêu cầu thành công, bị từ chối và chuyển nhân viên.

**Tiêu chí nghiệm thu**

- `hủy đơn` trả danh sách có tên món để khách chọn.
- `hủy đơn Combo chăm sóc da cơ bản` hủy đúng đơn chứa món đó.
- `hủy đơn Telegram` chỉ lọc các đơn Telegram thuộc customer hiện tại.
- Không thể hủy đơn của customer/tenant khác.

### BUG-011 – Phân biệt actor trong Unified Timeline (P1)

**Bằng chứng**

- Tin do bot/hệ thống tạo trong timeline bị hiển thị dưới `Khách hàng`.
- Tin nhân viên, bot và system event chưa có nhãn nhất quán nên khó biết ai đang chat.

**Hành vi đúng**

- `sender_type=customer` → Khách hàng.
- `sender_type=bot` → Bot chat.
- `sender_type=staff` + tên nhân viên → Nhân viên · <tên>.
- `sender_type=system` → Hệ thống (chỉ dùng cho audit/event, không phải tin tư vấn).
- Timeline phải giữ `actor_type`, `user_id`, route bot và correlation id để truy vết.

### BUG-012 – Khoảng trống Inbox và căn chỉnh UI (P2)

**Bằng chứng**

- Khi chưa chọn hội thoại, khu vực giữa Inbox và Customer 360 để trống quá lớn.
- Một số màn hình quản trị/form/bảng chưa căn giữa, chiều rộng cột và khoảng cách không đồng đều.

**Hành vi đúng**

- Hiển thị empty state có hướng dẫn ngắn, căn giữa theo panel, không để “cục” khoảng trắng không có ngữ nghĩa.
- Các panel Inbox, hội thoại và Customer 360 dùng grid/flex ổn định; không làm vỡ ở 1440/1280/1024/mobile.
- Nút hành động không bị ép xuống nhiều dòng; bảng có scroll ngang khi cần.

### BUG-013 – RAG/combo không trả đúng giá món lẻ và mức chênh (P1)

**Hành vi đúng**

- Khi hỏi combo gồm gì: trả đúng thành phần từ catalog/metadata.
- Khi hỏi mua một món lẻ trong combo: trả giá lẻ, tồn kho và giải thích giá combo khác bao nhiêu.
- Khi khách đổi từ combo sang món lẻ: hủy quote cũ đúng cách, không giữ nhầm sản phẩm/số lượng.
- Không dùng chunk RAG cũ để trả giá/tồn kho khi dữ liệu catalog hiện tại có sẵn.

### BUG-014 – Gợi ý sản phẩm bị mất hoặc lặp catalog (P1)

**Hành vi đúng**

- Câu hỏi chung → catalog gọn, không lặp nhiều lần cho cùng một inbound.
- Câu hỏi có sản phẩm cụ thể → product card/quote cụ thể.
- Nếu sản phẩm hết hàng/không tồn tại → báo đúng trạng thái và gợi ý sản phẩm gần nhất hoặc hỏi lại.
- Không để route RAG, customer collection và catalog cùng gửi nhiều phản hồi cho một inbound.

### BUG-015 – Customer 360 hiển thị quá nhiều contact/địa chỉ (P2)

**Bằng chứng**

- Sau khi khách nhập thông tin cho nhiều đơn, card hiển thị liên tiếp nhiều dòng `Email` và `Số điện thoại`, kể cả các giá trị trùng nhau.
- Địa chỉ giao hàng giống nhau cũng lặp nhiều lần, làm card kéo dài và khó thấy thông tin chính.

**Nguyên nhân cần sửa**

- UI đang render toàn bộ `customer360.contacts` và `customer360.addresses` theo từng bản ghi lịch sử.
- Chưa có lớp hiển thị phân biệt “thông tin chính” với “lịch sử thông tin”.

**Cách xử lý đề xuất**

1. Dedupe theo `kind + masked_value` ở lớp hiển thị; không xóa dữ liệu lịch sử trong database.
2. Mặc định chỉ hiển thị một Email chính, một số điện thoại chính và một địa chỉ mặc định.
3. Các giá trị khác gom vào `Thông tin khác (n)` / `Địa chỉ cũ (n)` dạng accordion hoặc modal.
4. Với mỗi dòng chính, hiển thị trạng thái xác minh mới nhất; không lặp trạng thái cho cùng một giá trị.
5. Giới hạn chiều cao card và cho phép xem thêm, tránh đẩy Unified Timeline ra khỏi màn hình.

**Tiêu chí nghiệm thu**

- 10 bản ghi contact trùng chỉ còn 1 dòng chính trong card.
- Địa chỉ trùng chỉ hiển thị một lần và vẫn giữ nhãn `Mặc định`.
- Người dùng vẫn xem được lịch sử đầy đủ khi bấm “Xem thêm”.
- Tên khách vẫn hiển thị đầy đủ; email/số điện thoại tiếp tục được che.
