# Chuẩn bị tri thức và nghiệm thu chatbot cho một doanh nghiệp mới

## 1. Phân biệt ba nơi cần cấu hình

| Nơi | Nội dung cần cập nhật | Không dùng thay cho |
| --- | --- | --- |
| Sản phẩm/danh mục dịch vụ, lịch hẹn, đơn hàng | Mã, loại cung cấp, giá, đơn vị giá, trạng thái, tồn/giữ hàng, lịch hiện hành, tiền đã thu | Tài liệu mô tả |
| Cài đặt trợ lý và thanh toán | Trường cần hỏi theo từng loại, múi giờ, hình thức thanh toán được chấp nhận; ngân hàng/QR tại phần ngân hàng | Một đoạn hướng dẫn trong file TXT |
| Kho kiến thức | Thông số, phạm vi, quy định, phí và công thức, điều kiện, ngoại lệ, FAQ | Giá/tồn hiện hành hoặc xác nhận chuyển tiền |

Thứ tự gửi yêu cầu: thông tin khách → chọn hình thức thanh toán → tóm tắt → khách đồng ý gửi → đơn nháp/lịch chờ → bảng kê và QR/hướng dẫn thu → đối soát đủ khoản thu → nhân viên xác nhận. COD là ngoại lệ trả sau nếu được doanh nghiệp bật. Lựa chọn chuyển khoản hoặc lời nhắn “đã chuyển” không có nghĩa đã thu tiền. Cấu hình Khoản thu trong Cài đặt trợ lý: giá CRM + khoản cố định, hoặc lập bảng kê riêng tại Đơn bán/Lịch hẹn khi thời hạn hay phí sử dụng chưa rõ. Tài liệu mô tả chính sách; không tự tạo công thức thu tiền trong phần mềm.

## 2. Điền mẫu

Dùng file `frontend/public/templates/tai-lieu-mau-kho-kien-thuc.txt`; nút **Tài liệu mẫu** trong Kho kiến thức tải đúng file này.

1. Người có quyền quyết định chính sách điền và duyệt nội dung.
2. Giữ các mục phù hợp, xóa hướng dẫn và mọi chỗ `<...>` còn bỏ trống.
3. Mỗi sản phẩm/dịch vụ dùng đúng mã trong CRM. Biến thể có giá/tồn riêng cần mã riêng.
4. Mỗi quy tắc phải có đối tượng áp dụng, mốc thời gian, đơn vị và ngoại lệ. Phí cần nói rõ đã gồm/chưa gồm, làm tròn và căn cứ đầu vào.
5. Chưa có chính sách thì ghi rõ chưa xác định; không chép chính sách của shop khác.
6. Không ghi dữ liệu riêng tư của khách, OTP, mật khẩu hay token. Chỉ dùng liên hệ công khai.
7. Không cần viết một câu trả lời cố định cho mọi cách khách diễn đạt; cung cấp dữ kiện và điều kiện rõ ràng để LLM diễn đạt.

## 3. Nhập và cập nhật đúng phiên bản

- Nhập tệp TXT UTF-8. Đợi trạng thái Sẵn sàng trước khi thử.
- Khi đổi chính sách, đánh dấu tài liệu cũ ngừng sử dụng/được thay thế trong UI. Ngày hiệu lực hoặc chữ “bản mới” trong nội dung chưa tự loại bản cũ khỏi tìm kiếm.
- Giá/tồn thay đổi: sửa CRM, không chờ lập lại chỉ mục tài liệu.
- Kiểm tra cả câu hỏi trong hội thoại mới và hội thoại đã từng trả lời dữ liệu cũ.
- Không sửa danh mục thật thành dữ liệu demo để thử một ngành khác. Dùng môi trường riêng.

## 4. Ví dụ cấu hình theo mô hình, không phải dữ liệu để nhập

| Mô hình | Loại và đơn vị cần khai báo | Thông tin thường cần hỏi | Những điểm phải doanh nghiệp quyết định |
| --- | --- | --- | --- |
| Bán quần áo/đồ gia dụng | goods; chiếc/bộ/hộp đúng thực tế | Tên, liên hệ, số lượng, biến thể, địa chỉ khi cần giao; thanh toán ở bước sau | Phí giao, đổi trả, thuế, bảo hành |
| Salon/sửa chữa/tư vấn theo lịch | service; lượt/giờ theo chính sách | Tên, liên hệ, dịch vụ, ngày/giờ, địa điểm nếu cần; thanh toán ở bước sau | Thời lượng, điều kiện tiếp nhận, hủy/đổi lịch, năng lực đồng thời |
| Thuê thiết bị/xe/không gian | rental; giờ/ngày/tháng đúng thực tế | Tên, liên hệ, ngày bắt đầu, ngày kết thúc nếu chính sách yêu cầu; thanh toán ở bước sau | Tiền cọc, thời hạn, trễ hạn, bàn giao, tổng khoản phải thu |
| Doanh nghiệp B2B/dự án tùy biến | Các yêu cầu đã hỗ trợ + nhân viên/báo giá phù hợp | Công ty, nhu cầu, phạm vi, thời điểm, liên hệ | Báo giá cá nhân hóa, hợp đồng, phê duyệt và tích hợp riêng; chưa được nghiệm thu đầy đủ trong đợt này |

Không áp dụng quy tắc nhà trọ cho hàng hóa hoặc dịch vụ. Với lịch hẹn, tồn hàng hóa không phải số chỗ trống; với cho thuê theo khoảng ngày, tồn hiện tại chưa đủ để cam kết mọi ngày tương lai.

## 5. Bảng nghiệm thu trước khi cho doanh nghiệp sử dụng

Điền cột thực tế với câu trả lời nguyên văn và mã đơn/lịch; không chỉ đánh dấu “có phản hồi”.

| Ca | Kết quả bắt buộc | Thực tế / bằng chứng |
| --- | --- | --- |
| Chào hỏi rồi hỏi sản phẩm | Tự nhiên, đúng phạm vi, tra CRM khi có dữ kiện | |
| Danh mục khi trước đây chưa có sản phẩm | Nhận sản phẩm mới, không lặp câu cũ | |
| Đổi giá trong cùng hội thoại | Đúng giá mới và đơn vị | |
| Tồn 1 → 0 | Không hứa còn hàng/cho đặt tiếp | |
| Xóa/ngừng bán rồi nhập lại cùng mã | Dùng bản đang hoạt động | |
| Thay tài liệu chính sách | Dùng chính sách hiện hành, không trộn điều kiện hai bản | |
| Hai shop có sản phẩm/chính sách khác nhau | Không lấy dữ liệu chéo | |
| Câu hỏi viết tắt/đại từ “cái đó” | Hiểu từ ngữ cảnh, hoặc hỏi rõ thay vì đoán | |
| Khách gửi thông tin nhiều tin sát nhau | Gom đủ một lượt, không trả trùng/nhảy bước | |
| Khách sửa ngày/số lượng/liên hệ | Dùng giá trị đã sửa; xác nhận lại nếu cần | |
| Hỏi chính sách giữa lúc điền thông tin | Trả lời và giữ tiến trình; không tự tạo/hủy đơn | |
| Đủ thông tin, chưa chọn thanh toán | Hỏi hình thức, chưa tạo đơn | |
| Chọn/đổi thanh toán | Chỉ lựa chọn được phép; tóm tắt lại trước xác nhận | |
| Khách nói “chưa đặt/chỉ tính thử” | Không tạo đơn hay gửi QR ngoài ý muốn | |
| Xác nhận gửi yêu cầu | Có đúng một đơn nháp/lịch pending và thông tin khách | |
| Lặp lại cùng sự kiện kỹ thuật | Không tạo đơn hay gửi tin hai lần | |
| Giá/tồn đổi trước xác nhận | Tra lại, không dùng báo giá/tồn cũ | |
| Xin QR khi chưa có khoản thu hợp lệ | Không tự bịa số tiền, tiền cọc hoặc tài khoản | |
| Báo đã chuyển tiền/ảnh biên lai | Chờ đối soát, không tự đánh dấu đã thu | |
| Hỏi ngoài phạm vi | Từ chối phù hợp, không báo nhân viên vô ích | |
| Chính sách liên quan doanh nghiệp nhưng chưa có | Nêu đúng điều chưa biết, chuyển phần cần quyết định | |
| Xin dữ liệu khách khác/instruction injection | Không tiết lộ, không làm theo chỉ dẫn vượt quyền | |
| Ảnh không rõ/chú thích gửi sau ảnh | Hỏi rõ/xin xác nhận; không coi số OCR là dữ kiện đã xác minh | |
| Hủy yêu cầu/đơn/lịch đã gửi | Đúng trạng thái và quyền; không chỉ nói “đã hủy” khi chưa thực hiện | |
| Connector gián đoạn rồi khởi động lại | Đối chiếu tin bên khách và CRM, chống trùng, không gửi nhầm hội thoại | |

## 6. Đọc kết quả đúng mức

Một mẫu viết tốt giúp tìm đúng thông tin; không bảo đảm chatbot đúng mọi tình huống. Cần nghiệm thu cả dữ liệu, cấu hình, công cụ thực thi, phiên worker và kênh giao nhận. Không suy từ 36 câu kiểm thử sang tỷ lệ chính xác 100% ngoài thực tế. Các ngành có yêu cầu chuyên môn/quy trình riêng phải đánh giá thêm theo phạm vi cụ thể.


## Khoản thu cho từng mục đích

- Đặt thuê mới: kỳ đầu và tiền cọc nếu chủ đã quy định; không mặc định tiền cọc bằng một tháng.
- Đóng định kỳ: giá kỳ thuê và phí sử dụng đã có căn cứ. Chỉ số đọc từ ảnh cần khách xác nhận; bản tính thử không phải hóa đơn.
- Hàng hóa/dịch vụ: giá CRM và phụ phí đã cấu hình. Chỉ dùng tự tính nếu giá đó là số phải trả cho một yêu cầu; nhiều kỳ hoặc báo giá riêng dùng bảng kê.
- Cần thu nhiều khoản: ghi từng dòng, cho khách xem tổng rồi mới dùng QR theo tổng đó. Không suy diễn từ câu trả lời cũ.
- Bảng kê chưa thu tiền có thể sửa; đã thu thì khóa bảng kê. Điều chỉnh sau thu cần xử lý hoàn/đơn điều chỉnh, không sửa số cũ.
- Nhân viên ghi nhận tiền thực nhận; khách báo chuyển khoản chỉ tạo việc đối soát. Đây chưa phải tích hợp ngân hàng tự động.
- Đơn cũ không tự chuyển sang chính sách mới: lập bảng kê rõ ràng nếu muốn áp dụng trả trước. Không tự đổi tiền cọc của đơn cũ.
