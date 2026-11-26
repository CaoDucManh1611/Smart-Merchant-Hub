# Kiểm tra và sửa hội thoại đặt lịch dịch vụ — 25/11/2026

Đã chạy lại đúng sáu câu theo thứ tự người dùng cung cấp. Sau sửa, bot nhận lời chào, liệt kê ba dịch vụ và chọn đúng dịch vụ để thu thập thông tin đặt lịch. Chọn dịch vụ chỉ mở hoặc cập nhật yêu cầu đang soạn; chưa xác nhận lịch hẹn.

## Phạm vi và dữ liệu kiểm tra

- Replay dùng SQLite riêng, không đọc/ghi dữ liệu khách hàng đang chạy và không gửi tin nhắn Telegram thật.
- Hai lần BEFORE/AFTER dùng cùng snapshot 24 sản phẩm của lần kiểm tra trước và cùng ba dịch vụ dựng từ tên, giá, thời lượng trong đoạn hội thoại người dùng gửi. Các dịch vụ không được lấy từ một lần đọc cơ sở dữ liệu đang chạy.
- Ba ID `101`, `102`, `103` là ID cục bộ của fixture, không đại diện cho ID dịch vụ trên hệ thống thật.
- Cấu hình kiểm tra bật danh mục sản phẩm và đặt lịch dịch vụ. Mã nguồn được chụp riêng trước mỗi lần chạy; hash nguồn ổn định trong toàn bộ lần AFTER.
- Bộ đếm đo số lần gọi provider thực tế. Harness giới hạn tối đa sáu lần và dừng gọi thật sau khi gặp HTTP 429.

| Ref trong fixture | Dịch vụ | Giá | Thời lượng |
| --- | --- | ---: | ---: |
| `service:101` | Tư vấn lựa chọn sản phẩm chăm sóc da cơ bản | 99.000 đồng | 30 phút |
| `service:102` | Hướng dẫn thực hành quy trình chăm sóc da hằng ngày | 149.000 đồng | 45 phút |
| `service:103` | Tư vấn bộ sản phẩm chăm sóc cá nhân theo ngân sách | 199.000 đồng | 60 phút |

## Kết quả BEFORE

Lần chạy mã nguồn trước sửa thu được:

| Lượt | Câu hỏi nguyên văn | Kết quả thực tế | Gọi provider thật |
| --- | --- | --- | ---: |
| 1 | `/start` | `dialogue_out_of_scope`; trả lời giới thiệu phạm vi trợ lý thay vì lời chào | 1 |
| 2 | `xin chafo` | `dialogue_out_of_scope`; trả lời giới thiệu phạm vi trợ lý thay vì lời chào | 1 |
| 3 | `ban dang co dich vu gi` | HTTP 429 ở bước phân loại danh mục; phản hồi báo trục trặc | 1 |
| 4 | `toi muon dat lich hen cho dich vu tu van lua chon cham soc da co ban` | `ProviderCircuitOpen`; phản hồi báo trục trặc | 0 |
| 5 | `tôi muốn đặt lịch hẹn tư vấn lựa chọn sản phẩm chăm sóc da cơ bản` | `ProviderCircuitOpen`; phản hồi báo trục trặc | 0 |
| 6 | `tôi muốn đặt lịch hẹn Hướng dẫn thực hành quy trình chăm sóc da hằng ngày` | `ProviderCircuitOpen`; phản hồi báo trục trặc | 0 |

Tổng cộng ba lần gọi provider thật; không có yêu cầu đang soạn, đơn hàng, lịch hẹn hoặc ticket mới. Lỗi provider khiến lần replay BEFORE chưa đi tới phần chọn dịch vụ; không dùng lần chạy này để khẳng định đã tái hiện phản hồi sai sản phẩm trong hội thoại gốc. Các lỗi định tuyến được tái hiện riêng bằng kiểm thử offline trên mã nguồn BEFORE.

## Sáu phản hồi AFTER

1. `/start`

   > Chào bạn! Mình có thể giúp bạn tìm sản phẩm hoặc tư vấn đơn hàng hôm nay nhé.

2. `xin chafo`

   > Chào bạn! Mình có thể giúp bạn tìm sản phẩm hoặc tư vấn đơn hàng hôm nay nhé.

3. `ban dang co dich vu gi`

   > Shop hiện đang cung cấp các dịch vụ sau:
   >
   > • Hướng dẫn thực hành quy trình chăm sóc da hằng ngày — 149.000 đồng · 45 phút
   >
   > • Tư vấn bộ sản phẩm chăm sóc cá nhân theo ngân sách — 199.000 đồng · 60 phút
   >
   > • Tư vấn lựa chọn sản phẩm chăm sóc da cơ bản — 99.000 đồng · 30 phút
   >
   > Bạn muốn tìm hiểu hoặc đặt lịch dịch vụ nào ạ?

4. `toi muon dat lich hen cho dich vu tu van lua chon cham soc da co ban`

   > Mình đang hỗ trợ bạn đặt Tư vấn lựa chọn sản phẩm chăm sóc da cơ bản. Bạn cho mình thêm Họ tên, Số liên hệ, Thời gian mong muốn nhé.

5. `tôi muốn đặt lịch hẹn tư vấn lựa chọn sản phẩm chăm sóc da cơ bản`

   > Mình đang hỗ trợ bạn đặt Tư vấn lựa chọn sản phẩm chăm sóc da cơ bản. Bạn cho mình thêm Họ tên, Số liên hệ, Thời gian mong muốn nhé.

6. `tôi muốn đặt lịch hẹn Hướng dẫn thực hành quy trình chăm sóc da hằng ngày`

   > Mình đang hỗ trợ bạn đặt Hướng dẫn thực hành quy trình chăm sóc da hằng ngày. Bạn cho mình thêm Họ tên, Số liên hệ, Thời gian mong muốn nhé.

Lượt 4 tạo một phiên `business_request` đang thu thập, `current_field=name`, `offering_ref=service:101`. Lượt 5 giữ đúng phiên và dịch vụ. Lượt 6 đổi phiên đó sang `service:102`, dùng quy tắc đặt lại thông tin và xác nhận của luồng yêu cầu hiện có. `last_result.offering.kind` là `service`. Wrapper của graph vẫn trả `status=graph_answer`, `session_id=0`, `current_field=null`; trạng thái đang thu thập được xác minh từ phiên đã lưu, không đổi tên trạng thái trong kết quả ghi nhận.

Toàn bộ sáu lượt AFTER có **0 lần gọi provider**, **0 đơn hàng**, **0 lịch hẹn**, **0 ticket**; bot vẫn ở chế độ `auto`; tồn kho và số lượng giữ chỗ không đổi.

## Phần đã sửa

- Nhận `/start` cùng cú pháp bot/payload hợp lệ và lời chào gõ nhầm `xin chafo`; lời chào trong khi đang thu thập giữ nguyên yêu cầu đang soạn.
- Câu có ý định dịch vụ hoặc đặt lịch đi qua quyền truy cập và luồng dịch vụ trước các nhánh tìm sản phẩm, gợi ý sản phẩm hoặc checkout. Cụm “lựa chọn sản phẩm” trong tên dịch vụ không tự mở luồng mua sản phẩm.
- Câu đặt lịch nêu rõ một dịch vụ được đối chiếu với danh mục đang hoạt động của đúng shop. Hỗ trợ tên không dấu và trường hợp bỏ hai từ “sản phẩm” trong tên dài của lượt 4.
- Tên đầy đủ được ưu tiên trước tên rút gọn và từ đệm. Không cắt chữ `A` ra khỏi tên `Massage A`, cũng không bỏ cụm `Dịch vụ` thuộc tên thật. Hai tên hoặc nhiều kết quả cùng phù hợp sẽ hỏi lại.
- Dịch vụ lưu bằng `AppointmentService` và dịch vụ lưu bằng `Product` đều giữ loại ref tương ứng. Câu có thêm thông tin liên hệ vẫn sử dụng bộ diễn giải và kiểm chứng dữ liệu hiện có.
- Ý định đặt lịch rõ ràng giữ workflow `appointment_booking` khi Sales Journey đề xuất nhánh báo giá/mua hàng. Ngược lại, câu “Tôi muốn mua Toner dưỡng ẩm 200ml thay vì đặt lịch dịch vụ” giữ luồng mua sản phẩm.
- Việc mở yêu cầu vẫn qua kiểm tra quyền truy cập, shop, trạng thái dịch vụ và phiên hiện có. Chưa có dữ liệu và xác nhận cần thiết thì không tạo giao dịch.

## Kiểm thử và giới hạn

- Bộ kiểm thử mới: **40/40 đạt trong 15,66 giây** trên nguồn cuối. Có ca nguyên văn sáu lượt, không dấu, đổi dịch vụ, tên mơ hồ/trùng một phần, dịch vụ không hoạt động/khác shop, dịch vụ dạng Product, liên hệ trong yêu cầu, phiên mua hàng đang tồn tại và xung đột Sales Journey. Mock sẽ báo lỗi nếu các câu rõ ràng gọi mô hình không cần thiết.
- Trước sửa, 21 trong 31 ca đầu thất bại trên nguồn BEFORE. Các ca bổ sung trong review tiếp tục tái hiện lỗi trước khi được sửa; lượt cuối chạy đủ 40 ca.
- Lượt mở rộng ban đầu chạy 25 module: **644 đạt, 48 thất bại**. Có một kỳ vọng cũ buộc gọi bộ phân loại dù câu đã nêu dịch vụ rõ ràng, và một kiểm tra đọc nguồn bị thiếu đường dẫn trong thư mục chạy tạm. Đã cập nhật đúng kỳ vọng đó, bổ sung đường dẫn nguồn cho harness; chín ca liên quan đều đạt. Không thay đổi các kiểm tra hành vi định tuyến hoặc không tạo checkout.
- Đối chiếu 24 module cũ trên snapshot nguồn BEFORE, giữ nguyên hash các file kiểm thử: **606 đạt, 46 thất bại**. Cả 46 ID lỗi trùng chính xác với bản hiện tại sau khi tách hai vấn đề test/harness nói trên; không có ID lỗi mới. Phân bố: 32 ca `test_conversation_graph`, 10 ca `test_customer_collection_flow`, 4 ca `test_catalog_search_contract`. Chi tiết và lỗi gốc nằm trong JSON đối chiếu.
- Các lỗi cũ chưa được sửa trong yêu cầu này. Bộ graph cũ có mock truy vấn thiếu `with_for_update`, cùng các lỗi checkout và kỳ vọng quota đã tồn tại trước sửa. Không coi kết quả kiểm thử rộng ban đầu là toàn bộ đạt.
- Khi bỏ 46 ca lỗi cũ, lượt chạy còn **645 đạt, 1 thất bại, 46 bỏ chọn** trong 81,85 giây. Ca bổ sung là `CustomerCollectionFlowTests.test_short_follow_up_uses_last_customer_product_mention`: chạy riêng trên BEFORE và AFTER đều lỗi `NoneType.current_field`; lớp BEFORE bỏ mười ca lỗi cũ cũng tái hiện đúng lỗi này (40 đạt, 1 thất bại, 10 bỏ chọn). Vì vậy đây là phụ thuộc trạng thái giữa các bài kiểm tra cũ, không phải lỗi mới của thay đổi dịch vụ. Đối chứng thêm `Conversation58` vẫn không chữa lỗi; không sửa giả dữ liệu hoặc thay đổi xử lý sản phẩm để ép bài này đạt. Tổng số ca cũ tách riêng khi chấp nhận là **47**.
- Lượt chấp nhận cuối trên đủ 25 module: **645 đạt, 47 bỏ chọn trong 81,31 giây**, process thoát mã 0. Danh sách 47 ca tách riêng và lý do nằm trong `rag-dat-lich-dich-vu-regression-exclusions-20261125.json`; không tính chúng là ca đạt. Kết quả 645 đã bao gồm 40 ca mới.
- Lần replay AFTER là một bài capture tích hợp đạt trong 23,38 giây; sáu lượt có phản hồi và trạng thái thực tế trong JSON. Đây là kiểm tra trên dữ liệu dựng riêng, chưa phải cuộc trò chuyện gửi trực tiếp qua Telegram.
- Bốn file ứng dụng và file kiểm thử mới đã kiểm tra cú pháp Python; `git diff --check` đạt. Rà soát độc lập không còn vấn đề đáng kể trong phạm vi thay đổi.

## Áp dụng vào hệ thống đang chạy

Đã nạp lại backend và worker của Docker project `smart-merchant-hub-runtime` sau khi mọi tiến trình kiểm thử và replay kết thúc. Kiểm tra lúc **17:30 ngày 25/11/2026 (UTC+7)**: cả hai container đều `running`, `healthy`, `failing_streak=0`. `/health` trả `status=ok`, `loaded_revision=source_revision=bb37335a3d00c2e8`. Bản đang chạy đã nạp đúng mã nguồn mới.

## Bằng chứng

- BEFORE: `rag-dat-lich-dich-vu-before-20261125.json`, SHA-256 `dbdc12ab4aafd7f9868f68573daddb821aa505457cd2fac291f8dd7a3be5d4b4`.
- AFTER: `rag-dat-lich-dich-vu-after-20261125.json`, SHA-256 `959a6b7e172002bdd375e504028b7b5c84f7faa2b2c3c1d728e1a63aacd6c70d`.
- Kiểm thử mới: `backend/tests/test_service_booking_dialogue_regression.py`.
- Kết quả hồi quy ban đầu: `rag-dat-lich-dich-vu-initial-regressions-20261125.xml`.
- Baseline kiểm thử cũ: `rag-dat-lich-dich-vu-baseline-regressions-20261125.xml`; đối chiếu: `rag-dat-lich-dich-vu-baseline-comparison-20261125.json`.
- Đối chứng ca phụ thuộc trạng thái: `rag-dat-lich-dich-vu-order-dependency-20261125.json` và `rag-dat-lich-dich-vu-order-dependency-baseline-20261125.xml`.
- Kết quả chấp nhận cuối: `rag-dat-lich-dich-vu-regressions-20261125.xml`; danh sách tách riêng: `rag-dat-lich-dich-vu-regression-exclusions-20261125.json`.
- Kiểm tra runtime sau khi nạp: `rag-dat-lich-dich-vu-runtime-20261125.json`.
- Nguồn AFTER: `conversation_graph.py` = `d3051c039a9a19983f65959e7fdf088cc11a1334aa31a2b724c8a7017416cdc5`; `business_request.py` = `01ad38d385601b91aa3350bb6557b84deb8da3c19d37ef1f03a0d2c6b7f7e78e`.
