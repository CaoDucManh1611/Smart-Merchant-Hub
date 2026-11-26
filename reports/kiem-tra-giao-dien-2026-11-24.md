# Báo cáo rà giao diện Smart Merchant Hub

- Thời điểm: 24/11/2026 (giờ Việt Nam)
- Phạm vi: giao diện đang chạy tại `http://localhost:5173/`.
- Cách làm: mở lần lượt các mục điều hướng chính; xem dữ liệu/trạng thái; thử bộ lọc chưa đọc, danh sách kênh, tải thêm sản phẩm và làm mới báo cáo.
- Không sửa mã nguồn. Không tạo/sửa/xóa dữ liệu, không đổi trạng thái đơn/lịch, không ghi nhận thanh toán/hoàn tiền, không gửi tin ra kênh thật.

## Kết luận

Các trang chính đều mở được và có nội dung. Một số thao tác xem như lọc hội thoại, tải thêm sản phẩm và làm mới báo cáo hoạt động. Tuy vậy, dữ liệu hiện tại chưa sạch để trình diễn liền mạch và có ít nhất hai mâu thuẫn trạng thái cần được kiểm tra trước buổi bảo vệ. Đây là rà soát giao diện và thao tác an toàn, chưa phải kiểm thử đầu-cuối mọi thao tác ghi dữ liệu.

## Phát hiện cần ưu tiên

### 1. Trạng thái Telegram không thống nhất — ưu tiên cao

- Trang **Trạng thái nhận tin**, sau khi bấm làm mới, báo Facebook, Instagram, Telegram và Zalo đang hoạt động; TikTok và Shopee đã ngắt.
- Trang **Kết nối mạng xã hội** lại báo Facebook, Instagram, Zalo đã kết nối nhưng Telegram đã ngắt; TikTok và Shopee không hoạt động.
- Phần tóm tắt của trang kết nối ghi 4/6 kênh hoạt động, trong khi trạng thái của từng thẻ chỉ thể hiện 3 kênh kết nối.
- Đã làm mới trang trạng thái nhận tin và vẫn thấy Telegram hoạt động, nên đây là mâu thuẫn tái hiện được giữa hai màn hình.

### 2. Lịch tương lai đang mang trạng thái hoàn tất — ưu tiên cao

- Bộ lọc **Sắp tới** hiển thị hai lịch ngày 25/11/2026 và 26/11/2026.
- Cả hai lịch có trạng thái **Hoàn tất**, dù ngày hẹn còn ở tương lai tại thời điểm kiểm tra.
- Một mục còn ghi “Chờ nhân viên xác nhận”; cả hai hiển thị “Chưa phân công”.
- Điều này làm người xem khó biết lịch nào thực sự cần xử lý. Không thay đổi trạng thái trong lần rà soát này.

### 3. Hàng đợi hỗ trợ có việc quá hạn và chưa phân công

- Trang Phiếu hỗ trợ hiển thị 5 phiếu, trong đó 2 phiếu quá hạn; có 1 phiếu quá hạn phản hồi và 2 phiếu quá hạn xử lý.
- Trang Việc cần xử lý hiển thị 2 phiếu quá hạn và 24 cuộc trò chuyện chưa phân công.
- Đây là trạng thái dữ liệu hiện tại, không kết luận lỗi phần mềm. Nếu dùng để trình diễn, nên kiểm tra các việc tồn đọng trước.

### 4. Dữ liệu hội thoại đang lẫn nhiều bộ dữ liệu thử

- Hộp thư có 24 cuộc trò chuyện từ nhiều kênh. Nội dung đang hiển thị gồm mỹ phẩm, phụ tùng xe và phòng trọ; một số hội thoại cũ còn câu trả lời báo lỗi/thiếu dữ liệu.
- Danh mục hiện hiển thị sản phẩm mỹ phẩm có ghi rõ dữ liệu giả lập. Trong cùng hộp thư có câu trả lời về phòng trọ và phụ tùng xe.
- Nếu đây là cùng không gian shop dùng để demo, dữ liệu lẫn ngành hàng có thể làm hội đồng khó theo dõi và khiến bot trông như đang trả lời nhầm shop. Hãy xác nhận đang dùng đúng shop/dataset trước khi trình bày.

### 5. Một số khối cài đặt còn ở trạng thái tải

Khi mở lại trang Cài đặt, **Lịch chăm sóc khách hàng** vẫn ghi “Đang tải lịch chăm sóc...” và **Chủ đề khách thường hỏi** vẫn ở trạng thái nút tắt “Đang tổng hợp...”. Không thể xác định chỉ từ giao diện đây là tác vụ nền chậm hay lỗi tải, nhưng trạng thái vẫn còn sau khi chuyển trang và quay lại.

## Những phần hoạt động theo quan sát

- Các mục chính đều mở được: Hộp thư, Danh sách khách hàng, Khách quan tâm, Phiếu hỗ trợ, Việc cần xử lý, Sản phẩm, Đơn bán, Lịch hẹn, Giờ làm việc, Quy tắc thời hạn, Kho kiến thức, Quy trình, Báo cáo, Kết nối mạng xã hội, Trạng thái nhận tin, Chọn gói dịch vụ và Cài đặt.
- Hộp thư tải đủ 24/24 cuộc trò chuyện. Bộ lọc **Chưa đọc 1** thu hẹp danh sách còn cuộc trò chuyện chưa đọc; danh sách đã được trả về **Tất cả 24**. Danh sách kênh lọc có Facebook, Instagram, Telegram, Zalo, TikTok và Shopee.
- Danh sách sản phẩm báo 40 sản phẩm; nút **Xem thêm** tăng số đang hiển thị từ 5 lên 10.
- Báo cáo tải được sau khi làm mới: 23 khách hàng, 24 cuộc trò chuyện, 13 đơn hàng và doanh thu hiển thị 1.709.000 đồng. Các phần báo cáo chi tiết có thể mở rộng.
- Kho kiến thức hiển thị 3 tài liệu, 77 đoạn thông tin, cả 3 tài liệu xử lý hoàn tất; hiện có 1 tài liệu đang sử dụng và 2 tài liệu tắt.
- Trang lịch hẹn và danh mục dịch vụ tải được; có 2 dịch vụ, một dịch vụ đang nhận lịch và một dịch vụ tạm ngừng.
- Trang Khách quan tâm và Quy trình hiện báo chưa có bản ghi; giao diện không báo lỗi.

## Giới hạn kiểm thử

Lần này chưa thực hiện các thao tác có thể tạo tác động thật hoặc làm thay đổi dữ liệu: gửi tin cho khách, tạo đơn/phiếu/lịch, sửa sản phẩm hoặc tồn kho, nhập/xuất dữ liệu, đổi trạng thái đơn/lịch, ghi nhận thanh toán/hoàn tiền, cấu hình kênh và lưu cài đặt. Vì vậy chưa thể kết luận các luồng ghi dữ liệu và tích hợp ngoài hệ thống hoạt động đầu-cuối.

## Kiểm tra bổ sung

- Menu Thao tác nhanh mở được và liệt kê các lối tắt tìm kiếm, mở hồ sơ 360, tạo phiếu nhanh và tạo đơn nháp nhanh. Không chọn lối tắt tạo dữ liệu.
- Bảng thông báo mở được nhưng báo **100 chưa đọc**; nút “Xóa tất cả” hiện diện. Không bấm nút xóa.
- Tìm “Toner” ở ô tìm kiếm trên cùng làm danh sách hội thoại còn một cuộc trò chuyện phù hợp và đồng thời điền cùng từ khóa vào ô “Tìm cuộc trò chuyện” trong hộp thư. Chưa xác minh tìm kiếm này có trả kết quả khách hàng/đơn hàng ở các màn hình khác; nên kiểm tra trước khi coi đây là tìm kiếm toàn hệ thống.
- Tìm theo tên trong Danh sách khách hàng trả các hồ sơ trùng tên và mở được hồ sơ 360. Đây có thể là nhiều hồ sơ/kênh khác nhau; cần rà ghép hồ sơ nếu muốn dùng danh sách này để trình diễn.

## Kiểm tra xác thực biểu mẫu và trợ lý hỏi đáp

### Biểu mẫu chưa điền

Đã bấm lưu khi để trống các biểu mẫu sau. Ứng dụng đưa tiêu điểm về trường bắt buộc; không thấy thông báo thành công hay bản ghi mới:

- Khách quan tâm → Nhu cầu khách hàng
- Phiếu hỗ trợ → Tiêu đề
- Lịch hẹn → Khách hàng
- Quy trình → Tên quy trình
- Thêm dịch vụ → Tên dịch vụ
- Nhập sản phẩm thủ công → Mã sản phẩm (SKU); danh sách vẫn báo 10/40 sản phẩm

### Hỏi đáp kho thông tin

Dùng ba câu hỏi mẫu trong **Trợ lý hỏi đáp** nội bộ, không gửi tin cho khách:

- **Danh sách sản phẩm & Giá:** trả về 20 mặt hàng/biến thể, trong khi danh mục sản phẩm báo 40. Câu trả lời gọi đây là “các sản phẩm” mà không nói danh sách đã rút gọn; cần kiểm tra để khách không hiểu nhầm là danh mục đầy đủ.
- **Chính sách đổi trả** và **phí giao hàng:** trợ lý không tìm thấy nguồn đủ tin cậy và đề nghị nhân viên xác minh. Đây là phản hồi an toàn khi thiếu chính sách cụ thể.
- Với câu hỏi phí giao hàng, phần **Nguồn tham khảo** hiển thị tài liệu kiến thức làm đẹp, đoạn về đơn vị catalogue/thuộc tính sản phẩm, độ phù hợp 30%; đoạn này không chứa chính sách giao hàng. Trợ lý vẫn từ chối kết luận, nhưng nguồn hiện ra chưa sát câu hỏi.

## Ghi nhận bổ sung ngày 24/11/2026

- **RFM:** trong Danh sách khách hàng, hồ sơ 360 hiển thị nhãn RFM; hồ sơ được mở khi kiểm tra đang có nhãn “RFM · Trung thành”. Đây là bằng chứng RFM xuất hiện ở phân nhóm/nhãn hồ sơ CRM. Chưa xác minh công thức tính, thời điểm cập nhật, hoặc RFM có tham gia trực tiếp vào logic chatbot/gợi ý sản phẩm hay không. Trang Khách quan tâm là luồng ghi nhận nhu cầu riêng; mô tả trên trang nói các ghi nhận đó có thể ưu tiên sản phẩm trong gợi ý 360 khi khách cho phép cá nhân hóa.
- **Báo cáo:** lọc ngày 24/11 cho 2 khách, 2 hội thoại, 12 đơn, 1.590.000 đồng; bỏ lọc và áp dụng lại trả về 23 khách, 24 hội thoại, 13 đơn, 1.709.000 đồng. Bộ lọc và thao tác áp dụng hoạt động nhất quán.
- **Gói dịch vụ:** trang tải được, hiển thị 5 gói và gói Premium hiện tại. Không thực hiện kích hoạt/nâng gói vì có thể thay đổi trạng thái dịch vụ hoặc phát sinh nghĩa vụ thanh toán.
- Sau kiểm tra, giao diện đã được đưa trở lại **Hộp thư khách hàng**, hiển thị 24/24 cuộc trò chuyện.

## Kiểm tra bổ sung: đơn hàng và danh mục sản phẩm

- Mở rồi đóng biểu mẫu **Nhập hóa đơn** mà không xác nhận. Biểu mẫu tự sinh mã đơn nháp và điền sẵn khách hàng/sản phẩm mẫu; sau khi đóng, bảng vẫn giữ 13 đơn và tổng doanh thu hiển thị 1.709.000 đồng. Không có đơn mới được tạo.
- Luồng **Nhập CSV đơn hàng** hiển thị hướng dẫn mẫu; nút xem trước/nhập bị khóa cho đến khi chọn tệp. Tài liệu CSV yêu cầu `order_number`, `customer_id`, `sku`, `quantity`, còn `conversation_id` tùy chọn. Chưa tải tệp hoặc chạy nhập thật.
- Mở lịch sử đơn **CHAT-5**: đã ghi hoàn tiền 257.000 đồng lúc 00:56, sau đó lúc 03:50 trạng thái lại chuyển từ “Đã xác nhận” sang “Đang đóng gói”. Trạng thái hiện tại là đang đóng gói trong khi khoản thanh toán ghi đã hoàn tiền đủ. Đây là bất nhất cần rà soát.
- Mở lịch sử đơn **CHAT-6**: ghi nhận thanh toán 142.000 đồng lúc 01:08, sau đó chuyển sang “Đã hủy” lúc 01:15; lịch sử đang hiển thị không có sự kiện hoàn tiền. Đơn hiện vẫn thể hiện đã thanh toán đủ. Tổng doanh thu 1.709.000 đồng khớp với các khoản chưa hoàn tiền và bao gồm 142.000 đồng của CHAT-6; cần xác định quy tắc doanh thu cho đơn đã hủy và đối soát khoản tiền này.
- Bảng sản phẩm tải thêm ổn định từng 5 mặt hàng mỗi lần bấm: 10 → 15 → 20/40. Chưa điều chỉnh giá, tồn kho, trạng thái hay nhập/xuất file.

## Ghi nhận bổ sung: kết nối, RAG và cài đặt

- **Trạng thái kênh chưa nhất quán:** trang “Trạng thái nhận tin” sau khi bấm Làm mới vẫn báo Facebook, Instagram, Telegram, Zalo đang hoạt động; TikTok và Shopee đã ngắt. Trang “Kết nối mạng xã hội” lại báo Facebook, Instagram, Zalo đã kết nối, Telegram đã ngắt, TikTok/Shopee không hoạt động; phần tóm tắt ghi 4/6 đang hoạt động trong khi các thẻ chỉ thể hiện 3 kênh đã kết nối. Shopee đang ngắt có thể là cấu hình chủ ý trước đó; riêng trạng thái Telegram và bộ đếm cần đối chiếu.
- **Tài liệu RAG đang dùng rất ít nội dung:** trang Kho kiến thức hiện có 3 tài liệu/77 đoạn. Chỉ `01-lam-dep-cham-soc-ca-nhan-kien-thuc.md` đang sử dụng với 2 đoạn; tài liệu hồ sơ và hỏi đáp 74 đoạn cùng tài liệu `N-----.txt` 1 đoạn đang ngừng sử dụng. Điều này phù hợp với việc hỏi chính sách bị từ chối hoặc nguồn tham khảo không sát câu hỏi; chưa thay đổi trạng thái tài liệu.
- **Hạn mức KB lệch giữa hai màn hình:** Kho kiến thức ghi 3/200 tài liệu và 77/10.000 đoạn, trong khi Cài đặt ghi 2/200 tài liệu và 59/10.000 mục kiến thức. Đã mở lại cả hai màn hình trong cùng lượt kiểm tra và con số vẫn khác nhau. Nút trạng thái trên phần hạn mức vẫn hiện “Đang tải...”.
- **Cài đặt RFM:** trang Cài đặt mô tả phân nhóm mức độ mua hàng dùng MiniBatchKMeans khi có ít nhất 20 khách đã mua và có consent; ghi rõ đây không phải dự đoán xác suất mua. Hồ sơ CRM đã mở trước đó có nhãn “RFM · Trung thành”. Chưa kiểm tra công thức hoặc việc chạy lại phân nhóm.
- **Cấu hình nghiệp vụ hiện tại:** mô hình đang chọn là “Dịch vụ theo lịch”, chưa chọn ngành nào; các công cụ Bán lẻ, Dịch vụ, Kho & tồn, Đơn hàng, Thanh toán, Gợi ý sản phẩm đều bật. Dữ liệu hiển thị trong hộp thư/danh mục gồm nhiều ngữ cảnh khác nhau (mỹ phẩm, phòng trọ, phụ tùng xe); nên xác nhận đây là dữ liệu demo chủ đích trước buổi bảo vệ.
- **Lưu ý bảo mật quan sát được:** xác thực 2 bước đang tắt; hệ thống ghi 40 phiên đăng nhập, 5/40 phiên đang hiển thị và cả 5 ghi chưa xác minh 2 bước. Mình không thu hồi phiên hay đổi cài đặt.
- **Trạng thái tải trong Cài đặt:** khi mở lại, lịch chăm sóc vẫn hiện “Đang tải lịch chăm sóc...”; nút tổng hợp chủ đề và nút nhật ký đều hiện trạng thái đang tải/đang tổng hợp dù bên dưới đã có chủ đề và lịch sử. Chưa thể kết luận dữ liệu không tải, nhưng chỉ báo tải chưa kết thúc.

## Kiểm tra chưa xác minh: tải hội thoại Zalo

- Chọn hội thoại Zalo của hồ sơ Đức Mạnh trong hộp thư; khung chi tiết đổi sang trạng thái “Đang tải tin nhắn...”.
- Các lần đọc lại giao diện/screenshot của tab ứng dụng hiện tại bị timeout, dù tab localhost vẫn còn mở. Vì vậy chưa xác minh được khung hội thoại có tự tải hoàn tất hay không, và chưa chạy thử nút gợi ý nội bộ ở hồ sơ 360. Không gửi tin và không thay đổi dữ liệu.
- Cần kiểm tra lại bằng trình duyệt khi tab phản hồi bình thường; chưa quy kết đây là lỗi của ứng dụng vì cũng có thể là sự cố lớp quan sát trình duyệt.

## Ghi nhận bổ sung: giới hạn phiên trình duyệt

- Thử đọc lại tab localhost đã đăng nhập trong trình duyệt Codex; công cụ chụp trạng thái giao diện hết thời gian chờ khi lấy DOM. Không thể xác nhận cuộc hội thoại Zalo đã tải hay chưa, và không dùng thao tác gửi tin để thử.
- Mở kiểm tra phụ bằng DevTools tạo ra một phiên trình duyệt riêng, chưa đăng nhập, nên chỉ thấy trang giới thiệu. Trang này tải được; console chỉ có thông báo Vite kết nối, request trang `/` trả 304 và `/api/onboarding/plans` trả 200. Kết quả này chỉ xác nhận trang công khai hoạt động, không chứng minh các chức năng sau đăng nhập.
- Vì dữ liệu hiện có gồm hội thoại/đơn thật và các luồng ghi có thể gửi tin ra Facebook/Zalo hoặc thay đổi doanh thu/tồn kho, chưa chạy tiếp CRUD, thanh toán/hoàn tiền, chatbot/kênh thật. Cần một shop hoặc bản sao cơ sở dữ liệu demo tách biệt để hoàn tất kiểm thử đầu-cuối an toàn.
- Không sửa mã nguồn và không thay đổi dữ liệu nghiệp vụ trong lượt kiểm tra này.

## Kiểm tra bổ sung: trang giới thiệu công khai

Do phiên app đã đăng nhập không đọc được DOM, mở một tab DevTools riêng đến `http://localhost:5173/`; tab này không có phiên đăng nhập và chỉ dùng để kiểm tra trang công khai.

- Năm mục FAQ đều mở được và hiện câu trả lời; mục “Trợ lý dùng kiến thức từ đâu?” khuyên chuẩn bị thông tin sản phẩm/tài liệu shop, kiểm tra nguồn và chuyển cho nhân viên khi cần.
- Ba tab minh họa “Hộp thư chung”, “Trợ lý kiến thức”, “Công việc mỗi ngày” chuyển panel và nội dung đúng theo lựa chọn.
- Nút đổi chế độ tối đổi trạng thái/nhãn; đã bật lại chế độ sáng và tải lại trang. Sau tải lại, tab “Hộp thư chung” được chọn và FAQ đóng như trạng thái mặc định.
- Sau tương tác không thấy cảnh báo/lỗi console; request đọc gói `/api/onboarding/plans` trả 200. Đây chỉ là kiểm tra giao diện công khai, không xác nhận chức năng sau đăng nhập.

## Lượt kiểm tra tiếp theo: phiên sau đăng nhập

- Kiểm tra lại tab `http://localhost:5173/` trong Codex; tab vẫn tồn tại nhưng đọc DOM tiếp tục timeout ở lệnh `DOMSnapshot.captureSnapshot` sau khoảng 23 giây.
- Chrome thường hiển thị ứng dụng trong một cửa sổ riêng, nhưng phiên đó không chia sẻ đăng nhập với tab Codex. Không đăng nhập lại hoặc dùng cửa sổ Codex desktop để điều khiển vì quy định của skill `computer-use` cấm tự động hóa giao diện Codex desktop.
- Do đó, phần kiểm tra công khai đã hoàn tất trong phạm vi có thể; phần chức năng sau đăng nhập vẫn chưa xác minh đầu-cuối. Cần phiên trình duyệt app có thể đọc được hoặc môi trường shop/DB kiểm thử riêng để tiếp tục mà không chạm dữ liệu thật.
