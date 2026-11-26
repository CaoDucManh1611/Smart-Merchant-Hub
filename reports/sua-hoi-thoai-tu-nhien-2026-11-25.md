# Sửa hội thoại tự nhiên — 25/11/2026

## Phạm vi
Giữ BM25 và kho tài liệu/vector hiện tại. Bổ sung catalog_dialogue.py trước các nhánh phân loại cũ khi quyền catalog cho phép. Cờ CATALOG_DIALOGUE_ENABLED mặc định false trong source để có đường quay lại; chỉ bật bằng cấu hình runtime sau kiểm tra.

## Thay đổi
- Một request AI ngắn đọc ý định và các trường: nhóm, sản phẩm được nhắc, ngân sách VND, nhu cầu, tham chiếu lịch sử, độ chắc chắn. Nhóm bị giới hạn bằng enum lấy từ danh mục thực tế; không thêm danh sách câu hỏi cố định vào if/regex.
- Giảm lượng lịch sử gửi AI xuống4 lượt ngắn, kèm trạng thái nhóm/ngân sách/shortlist; chỉ dùng ngữ cảnh gần15 phút. Câu mới được ưu tiên, nhóm mới không bị danh sách cũ chặn. Các câu sửa lời bot có thể lấy lại tiêu chí trước đó; lời staff không tự trở thành nhu cầu khách.
- Kiểm tra nhãn mâu thuẫn (social nhưng đồng thời xác định sản phẩm) bằng một lượt đọc lại có giới hạn. Schema sai có một lần thử lại có giới hạn; lỗi provider hoặc hiểu chưa chắc được hỏi làm rõ, không tự gợi ý top1.
- Request catalog_intent riêng dùng max_completion_tokens768 và reasoning_effort low với gpt-oss. Không đổi tùy chọn cho các request AI khác. Cache kết quả diễn giải cùng payload/model; giá/tồn vẫn được đọc mới mỗi lần.
- Backend kiểm tra shop, active, nhóm, giá/ngân sách, tồn sau giữ chỗ. Danh sách nhóm có thể hiện mặt hàng hết hàng kèm nhãn; gợi ý chỉ lấy hàng còn bán/còn hàng. Tên nhóm không tự chọn một biến thể. Không tìm được áo thì không thay bằng mỹ phẩm.
- Câu hỏi khả năng mua trong ngân sách không tạo đơn. Hỏi bán chạy dùng số khách riêng biệt và số lượng trên các đơn delivered/completed chưa refunded; không mở checkout. Đây là số liệu trên các đơn hiện có, không phải thống kê thị trường hoặc kỳ thời gian chưa được hỏi rõ.
- Cách dùng phải từ usage đã cấu hình đúng sản phẩm; hiện hồ sơ demo chưa có hướng dẫn xác nhận nên nói rõ thiếu, không đưa toner thay serum. Không bịa loại da phù hợp hoặc cách điều trị.
- Phàn nàn và xã giao không kích hoạt sản phẩm xếp hạng đầu. Phần xã giao dùng câu trung tính, còn cơ bản; không xem đây là đánh giá đạt mọi sắc thái cảm xúc.
- Chuyển nhân viên chỉ xác nhận sau khi backend chấp nhận ticket hợp lệ; tạm dừng bot bằng human mode. Người quản lý có thể bật bot lại trên giao diện khi muốn tiếp tục.
- Form checkout đang mở, số điện thoại/email trong form, ảnh, nghiệp vụ dịch vụ/đơn và chính sách chuyển tiếp về luồng hiện có. Luồng mua sản phẩm rõ được trả lại checkout cũ sau xác định đối tượng.

## Kiểm tra bằng hội thoại Oanh
Dùng corpus cố định57 tin tới ID17760, gộp thành27 lượt. Thêm9 cách diễn đạt khác và2 ca kiểm tra mua/dịch vụ =38 ca. Từng ca có cùng tiền tố lịch sử gốc, chạy graph và backend thật trong bản sao transaction tenant/platform; không gửi Zalo hay email, không tạo ticket/đơn ở dữ liệu thật.

Đã chạy nhiều lượt API thật trong quá trình sửa. Lượt xác minh cuối dùng lại kết quả diễn giải AI hợp lệ từ lượt trước để tái hiện ổn định, có6 lượt gọi compact AI mới và42 lần tái dùng (bao gồm đọc lại câu trước). Không phải38 lượt inference độc lập mới; không dùng điểm này để khẳng định AI hiểu đúng mọi câu tương lai. Backend và ràng buộc được chạy lại thật cho mọi trường hợp.

Các tiêu chí đã kiểm tra: đúng nhóm khi chọn dầu gội/dầu tẩy trang, không đổi áo thành toner, giữ son+100000 qua câu nối tiếp và lời phàn nàn, không giới thiệu món vượt ngân sách là phù hợp, không đổi hỏi serum thành gợi ý toner, không đổi hỏi bán chạy thành đặt đơn, không tư vấn loại da chưa có căn cứ, xử lý yêu cầu nhân viên sau xác nhận thật của tool trong bản sao. Câu xã giao chỉ kiểm tra không spam sản phẩm/không đưa thông tin sai; chưa đạt tiêu chí hội thoại người thật hoàn toàn.

## Khách mới: chuỗi dùng chính câu trả lời mới của bot
Tạo customer/conversation mới trong schema thử; lưu các tin giả lập và metadata trong bản thử để kiểm tra trạng thái:
1. Tư vấn son: liệt kê đúng son và giá.
2. “Mình chỉ có100k thôi”: giữ nhóm son, báo chưa có trong mức này.
3. “Vậy có cây nào vừa tiền mình không?”: vẫn giữ100k+son, không trả toner284k.
4. “Vậy tăng lên350k, gội đầu thì có loại nào?”: đổi nhóm/ngân sách, trả Dầu gội Tiêu chuẩn303000.
5. “Cho mình mua một chai loại vừa nói”: chuyển đúng quote mua1 dầu gội303000, chưa tạo đơn/thanh toán.
Các lượt mới dùng lời bot vừa sinh làm lịch sử, không dùng lại lời bot sai trong corpus gốc.

## Kiểm tra source
Bộ test catalog_dialogue kiểm tra ngân sách, nhóm, mặt hàng không có, hướng dẫn chưa xác nhận, phiên đang thu thập, chính sách/dịch vụ đi luồng cũ, mua hàng rõ, shortlist mới, nhãn mâu thuẫn, human mode sau ticket được chấp nhận. Các ca hồi quy mua/quote trước đó đã chạy cùng bộ test và đạt. Bộ test mới cuối cùng đạt26/26. Lượt chạy kết hợp trước đó đạt34 ca (23 ca mới tại thời điểm đó và11 ca hồi quy mua/quote).

## Cách ly và giới hạn
Các bảng/sequence được sao chép vào schema thử, sequence riêng được đặt cao hơn ID tối đa đã copy để tránh race khi live có tin mới. Hai transaction cuối rollback; không đổi hội thoại thật. Đây không phải phép thử connector giao tin end-to-end.

AI vẫn có thể hiểu sai câu chưa gặp và vẫn phụ thuộc hạn mức provider. Khi hết quota, hệ thống không bảo đảm trả lời đầy đủ; nó hỏi làm rõ hoặc nhờ hỗ trợ thay vì chọn sản phẩm tùy ý. Giá/công dụng chỉ chính xác theo thông tin shop đã nhập; demo không có tài liệu thành phần/cách dùng thật.

## Bằng chứng / quay lại
reports/oanh-semantic-final-20261125.json lưu38 kết quả và chuỗi5 lượt mới. Các JSON trial là dấu vết thử nghiệm, gồm lỗi đã sửa; không phải kết quả bản cuối.
backups/dialogue-before-fix-20261125.zip giữ bản gốc các file được thay trong đợt này. Các backup database và commit6276e40 từ trước vẫn giữ.
Để tắt riêng tính năng mới: đặt CATALOG_DIALOGUE_ENABLED=false trong backend/.env rồi recreate backend/worker bằng compose đang dùng. Không cần phục hồi toàn database hoặc xóa đơn mới để tắt tính năng.

## Trạng thái triển khai
Đã bật CATALOG_DIALOGUE_ENABLED=true và recreate backend/worker. Cả hai đọc flag true, retrieval bm25; backend /health trả status ok, loaded_revision khớp source_revision. Chưa kiểm tra gửi tin trực tiếp qua Zalo trong đợt xác minh này.

## Bổ sung lọc công dụng và giá
Bộ lọc dùng cả suitable_needs và benefits do shop nhập; không lấy warnings/usage làm khẳng định phù hợp. Giá và tồn vẫn lấy trực tiếp danh mục. Chỉ có ngân sách thì tiêu đề chỉ nói trong ngân sách, không tự nhận phù hợp nhu cầu. Bộ test product_profile đạt11/11; compile source đạt. Đã restart backend/worker.

## Hoàn tác theo yêu cầu
Đã hoàn tác riêng bổ sung lọc benefits và thay tiêu đề ngân sách của lượt sửa cuối, trở về logic suitable_needs trước đó. Các sửa hội thoại trước vẫn giữ.
