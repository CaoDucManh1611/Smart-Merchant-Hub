# Lộ trình làm RAG thông minh cho CRM đa nền tảng

Tài liệu này ghi lại thứ tự công việc để cải thiện trợ lý bán hàng của Smart Merchant Hub, từ dữ liệu shop, truy xuất, hiểu hội thoại đến vận hành an toàn trên Facebook, Instagram, Telegram, Zalo, TikTok và Shopee.

## 1. Nguyên tắc trước khi bắt đầu

RAG không phải là huấn luyện lại mô hình. Luồng hiện tại nạp tài liệu, chia thành các đoạn, tạo embedding, tìm bằng vector/từ khóa rồi đưa nguồn phù hợp cho mô hình trả lời. Chất lượng phụ thuộc trước hết vào dữ liệu đúng, định tuyến đúng và truy xuất đúng.

- Không đưa dữ liệu giả, dữ liệu công khai nhiều ngành hoặc dữ liệu của shop khác vào kho tri thức của shop thật. Chúng chỉ phù hợp làm dữ liệu kiểm thử.
- Không dùng RAG làm nguồn chuẩn cho tồn kho, giá hiện hành, đơn hàng, thanh toán hoặc trạng thái giao hàng. Các dữ liệu thay đổi này phải đọc từ cơ sở dữ liệu CRM qua công cụ có kiểm soát.
- Không nhúng toàn bộ lịch sử chat và đơn hàng vào vector để thay cho CRM. Chỉ lưu các sự kiện/fact có nguồn, thời điểm, quyền sử dụng và khả năng sửa/xóa rõ ràng.
- Một lớp hiểu hội thoại dùng chung cho mọi kênh; mỗi nền tảng chỉ là adapter nhận/gửi và chuẩn hóa sự kiện. Không tạo sáu bộ quy tắc trả lời tách biệt.
- Tài liệu tải lên là dữ liệu không đáng tin cậy, không phải chỉ thị cho mô hình. Nội dung yêu cầu bỏ qua quy tắc, tiết lộ dữ liệu hoặc gọi công cụ phải bị coi là prompt injection.

## 2. Hiện trạng đã kiểm tra

Mã nguồn hiện có pipeline nạp tài liệu qua hàng đợi, chunking theo cấu trúc, embedding local/Gemini/OpenAI, hybrid retrieval pgvector + từ khóa, dựng prompt, gọi LLM, kiểm tra câu trả lời/citation và handoff. Các điểm vào chính:

- RAG: backend/app/rag/loader.py, semantic_chunker.py, embedder.py, retriever.py, prompt_builder.py, answer_guard.py, llm_caller.py.
- Tích hợp trả lời/kênh: backend/app/services/channel_event_service.py, conversation_turn_service.py, auto_reply_service.py, chatbot_agent.py, channel_delivery.py.
- Bộ câu hỏi và vận hành: docs/chatbot-evaluation-set.jsonl, docs/chatbot-evaluation-answer-key.jsonl, docs/rag-learning-operations.md.

Bài chạy lexical fallback gần nhất được lưu tại docs/rag-evaluation-latest-report.json:

| Phần kiểm tra | Kết quả | Ý nghĩa |
|---|---:|---|
| Định tuyến 100 câu | 100/100 | Bộ phân loại tuyến xử lý xác định vượt qua; chưa chứng minh truy vấn CRM hoặc câu trả lời AI đúng. |
| Truy xuất trên bộ demo có nguồn | 39 câu có tài liệu đối chiếu; 1 câu về đơn hàng có cấu trúc được bỏ qua | Chỉ kiểm tra được câu có nguồn trong bốn tài liệu demo. |
| Recall nguồn trong 5 kết quả đầu | 68,85% (trước sửa: 59,02%) | Truy xuất dự phòng đã cải thiện; vẫn còn nguồn mong đợi bị bỏ sót. |
| Đủ tất cả nguồn mong đợi trong top 5 | 53,85% (trước sửa: 46,15%) | Cần tiếp tục cải thiện xếp hạng và tìm nguồn kết hợp. |
| Từ khóa bằng chứng xuất hiện trong top 5 | 54,69% (trước sửa: 45,31%) | Lexical fallback là đường dự phòng, không phải kết quả cuối khi embedding hoạt động. |
| Sinh câu trả lời bằng LLM | Chưa chạy | Chưa chấm độ đúng nội dung, citation hay khả năng bịa; lượt này không gọi dịch vụ AI. |

> Đây là baseline của chế độ lexical fallback chạy cô lập, không phải phép đo đầy đủ cho vector/hybrid retrieval khi cấu hình embedding thật đang hoạt động. Vì vậy phải đo riêng cả hai chế độ trước khi kết luận.

## 3. Lộ trình triển khai

### Giai đoạn 0 — Chốt dữ liệu chuẩn và bộ kiểm thử

1. Tách rõ dữ liệu theo nguồn:
   - Danh mục sản phẩm: SKU/biến thể, tên, giá, tồn kho, trạng thái bán — nguồn chuẩn là bảng sản phẩm/tồn kho.
   - Chính sách shop: giao hàng, đổi trả, bảo hành, thanh toán, thời hạn và ngoại lệ — chỉ dùng bản shop xác nhận.
   - Hướng dẫn/FAQ: nội dung ổn định, có người duyệt và ngày hiệu lực.
   - Đơn hàng/khách hàng/RFM: dữ liệu có cấu trúc trong CRM, không coi tài liệu RAG là bản ghi thật.
2. Mỗi tài liệu cần có shop sở hữu, nguồn, phiên bản/ngày hiệu lực, trạng thái duyệt và người chịu trách nhiệm. Tài liệu hết hiệu lực phải ngừng truy xuất hoặc được thay thế có kiểm soát.
3. Giữ bộ 100 câu hiện tại làm kiểm thử định tuyến/hành vi; bổ sung bộ câu có nguồn chuẩn và fixture riêng cho sản phẩm, tồn kho, đơn hàng và chính sách. Mỗi ca cần id, ý định mong đợi, dữ liệu fixture, nguồn mong đợi, điều bắt buộc/không được nói và hành động mong đợi.
4. Không chấm câu hỏi về dữ liệu động bằng câu trả lời cố định nếu fixture không được đóng băng. Ví dụ giá/tồn kho trong fixture phải có mốc thời gian và shop thử nghiệm xác định.

**Đạt khi:** mỗi ca kiểm thử có đáp án kiểm chứng được; không dùng dữ liệu thật của khách hàng để làm bộ mẫu; các câu chưa có nguồn chuẩn được đánh dấu handoff/clarify thay vì tự bịa.

### Giai đoạn 1 — Nâng chất lượng truy xuất RAG

Ưu tiên xử lý các ca còn thiếu nguồn trong báo cáo live; chú ý truy vấn sản phẩm/CSV và câu hỏi diễn đạt khác tài liệu.

1. Chạy cùng bộ dữ liệu bằng: lexical fallback, embedding/vector, và hybrid thực tế. Ghi lại cấu hình embedding, phiên bản chunker, top-k, ngưỡng, thời gian và mã tài liệu.
2. Tách truy xuất dữ liệu có cấu trúc khỏi truy xuất văn bản:
   - SKU/mã hàng khớp chính xác → truy vấn catalog trước.
   - Tên gần đúng/biến thể → chuẩn hóa dấu, viết tắt, mã và biến thể; nếu còn nhiều ứng viên thì hỏi lại.
   - Câu hỏi giải thích/so sánh/hướng dẫn → truy xuất tài liệu đã duyệt.
3. Với văn bản, giữ tìm kiếm kết hợp vector và từ khóa. Không để một đoạn trùng vài từ phổ thông lấn át đoạn chứa mã, điều kiện hoặc ngoại lệ. Thử rank fusion/reranking chỉ khi báo cáo chứng minh ranking hiện tại là nút thắt.
4. Giữ nguyên tên shop, tiêu đề, SKU, đường dẫn mục và ranh giới bảng khi tạo embedding; không gộp nhiều sản phẩm vào một chunk khiến giá/tồn kho lẫn nhau.
5. Sau mỗi thay đổi, chạy lại cùng bộ eval và so Recall@5, MRR, đủ nguồn top-5, độ trễ và số câu rỗng. Không thay model/chunker trên dữ liệu thật trước khi so sánh với baseline và có đường reindex/rollback.

**Đạt khi:** nguồn sản phẩm/chính sách đúng thường xuyên nằm trong top-k; không lấy nguồn của shop khác; câu không có dữ liệu tiếp tục trả trạng thái thiếu nguồn/handoff. Mục tiêu ban đầu đề xuất: Recall@5 ≥ 90% trên ca có nguồn biết trước; cần chủ shop duyệt ngưỡng trước khi dùng làm cổng phát hành.

### Giai đoạn 2 — Định tuyến ý định và công cụ đọc CRM

Tạo một luồng quyết định rõ ràng trước khi gọi RAG/LLM:

| Loại câu hỏi | Nguồn/xử lý đúng |
|---|---|
| Giá, SKU, biến thể, tồn kho hiện tại | Tra catalog/tồn kho theo business_id; không lấy số cũ từ chunk. |
| Mô tả, cách dùng, chất liệu, FAQ ổn định | RAG trên tài liệu đã duyệt; dẫn nguồn. |
| Đơn hàng, vận chuyển, lịch sử mua | Công cụ CRM, sau khi xác định đúng khách/hội thoại và áp dụng quyền truy cập. |
| Xác nhận mua, gom tên/điện thoại/địa chỉ/thanh toán | Luồng đơn hàng có trạng thái và biểu mẫu thu thập; hội thoại từng phần cập nhật cùng một bản nháp, không hỏi lại phần đã có. |
| COD/chuyển khoản/QR | Luồng thanh toán có cấu hình shop và kiểm tra server; không để mô hình tự xác nhận đã nhận tiền. |
| Hỏi mơ hồ, chính sách không có nguồn, an toàn sức khỏe/điện | Hỏi làm rõ hoặc chuyển nhân viên; không suy diễn. |
| Gợi ý theo lịch sử/RFM | Công cụ đọc phân khúc và catalog hiện tại; chỉ dùng fact được phép cá nhân hóa. |

Công cụ phải nhận business_id/tenant từ phiên đã xác thực, giới hạn trường được trả, timeout và ghi log an toàn. Không cho LLM tự tạo SQL, truy cập tenant khác hoặc thực hiện hành động ghi như xác nhận đơn/thanh toán.

**Đạt khi:** các intent quan trọng có route chính xác; giá/tồn kho/đơn hàng lấy từ fixture CRM; mọi tool call đều được tenant-isolation test; câu không rõ không bị ép thành ý định mua.

### Giai đoạn 3 — Ngữ cảnh nhiều lượt, ghi nhớ và RFM

- Dùng lịch sử hội thoại gần nhất để hiểu câu nối tiếp như “cái đó”, “lấy 2 cái”, nhưng giới hạn độ dài và chỉ lấy đúng business_id + conversation_id.
- Gộp tin nhắn gửi thành nhiều đoạn trong một khoảng ngắn theo cơ chế turn hiện có. Tránh trả lời mỗi mảnh một lần hoặc gửi lặp; khóa/idempotency phải theo lượt và hội thoại.
- Lưu customer fact dưới dạng có cấu trúc: giá trị, nguồn (khách nói/đơn đã hoàn tất/nhân viên nhập), thời điểm, độ tin cậy, thời hạn và trạng thái opt-out. Fact suy đoán không được biến thành sự thật.
- Tính RFM từ đơn hàng đã hoàn tất: Recency = số ngày từ lần mua gần nhất; Frequency = số đơn đủ điều kiện trong kỳ; Monetary = doanh thu thuần sau hoàn/huỷ theo quy tắc shop. Loại đơn huỷ/chưa thanh toán; quy tắc hoàn tiền phải được thống nhất.
- RFM là phép tính CRM có thể giải thích và cập nhật; không vector hóa điểm RFM như tài liệu. Chọn ngưỡng theo dữ liệu của từng shop, hiển thị lý do phân khúc, xử lý khách mới chưa có đơn và cho phép sửa/tắt cá nhân hóa.

**Đạt khi:** hội thoại nhiều tin điền đủ thông tin một lần; khách mới không bị gắn VIP; đơn hủy/hoàn không làm sai điểm; khách opt-out không bị dùng fact để cá nhân hóa.

### Giai đoạn 4 — Một trợ lý nhất quán trên các nền tảng

1. Mỗi connector chuyển tin vào sự kiện chuẩn chung: nền tảng, tài khoản shop, hội thoại, khách, message ID, thời điểm, văn bản, tệp đính kèm và trạng thái xử lý.
2. Chống trùng sự kiện đầu vào và chống gửi lặp đầu ra bằng khóa idempotency. Một lượt bot chỉ có một kết quả trả lời; retry gửi phải biết lần trước đã thành công hay chưa.
3. Chạy chung bộ intent/RAG/CRM tools; chỉ adapter chịu trách nhiệm giới hạn riêng của Facebook, Instagram, Telegram, Zalo, TikTok, Shopee (độ dài, cửa sổ nhắn tin, ảnh/voice, định dạng nút).
4. Với ảnh/voice: xác minh URL/tệp, tải an toàn, kiểm tra MIME/kích thước, OCR hoặc chuyển giọng nói thành văn bản trước khi tìm nguồn; giữ liên kết tới message gốc và không coi nội dung ảnh là chỉ thị hệ thống. Nếu nền tảng không hỗ trợ media đó, báo rõ hoặc đề nghị gửi dạng khác.
5. Handoff phải đổi chế độ bot, tạo dấu vết cho nhân viên và ngăn bot tiếp tục trả lời ngoài ý muốn. Không gửi dữ liệu nhạy cảm sang nền tảng không cần thiết.

**Đạt khi:** cùng một fixture cho kết quả nghiệp vụ tương đương trên mọi adapter hỗ trợ; không mất/nhân đôi tin; giới hạn media từng nền tảng được kiểm thử riêng; không gửi ra tài khoản thật trong QA.

### Giai đoạn 5 — Chất lượng câu trả lời, bảo mật và phát hành

- Prompt nói rõ thứ tự ưu tiên: quy tắc hệ thống → dữ liệu CRM có cấu trúc hiện hành → tài liệu shop đã duyệt → lịch sử liên quan. Trích dẫn chỉ được gắn nếu nguồn thật sự hỗ trợ mệnh đề.
- Chấm câu trả lời tách biệt với truy xuất: tính đúng sự kiện/giá, bao phủ yêu cầu, citation precision, không bịa, ngôn ngữ phù hợp, câu hỏi làm rõ/handoff và độ tự nhiên. Kiểm tra bằng so sánh với đáp án chuẩn và duyệt thủ công một mẫu.
- Thêm kiểm thử prompt injection trong tài liệu, rò rỉ giữa hai tenant, câu hỏi không có nguồn, dữ liệu lỗi thời, SKU gần giống, thiếu thông tin người nhận, media độc hại và retry webhook.
- Log run_id, phiên bản prompt/model/chunker, nguồn chunk ID, route/tool, độ trễ, trạng thái/handoff và chi phí; che PII, không lưu secret hoặc toàn bộ nội dung chat nếu không cần.
- Bắt đầu bằng tenant demo và một nhóm nhỏ ca kiểm thử; giới hạn số gọi AI/ngân sách. Sau đó canary, theo dõi lỗi và có thể quay lại phiên bản prompt/index trước. Chỉ mở auto-reply sau khi nhân viên duyệt đạt.

**Cổng phát hành đề xuất:** 0 lỗi rò rỉ tenant; 0 giá/tồn kho/đơn hàng bịa trong bộ kiểm thử; 100% citation trỏ tới nguồn tồn tại; đạt ngưỡng retrieval đã thống nhất; auto-order/payment không ghi trạng thái nếu chưa có xác nhận từ backend; kiểm tra gửi lặp và handoff qua QA.

## 4. Lệnh kiểm tra hiện có

Chạy từ thư mục gốc smart-merchant-hub trong PowerShell:

~~~powershell
python scripts/evaluate_rag_set.py
python scripts/evaluate_rag_quality.py
python -m pytest backend\tests\test_rag_tenant_isolation.py backend\tests\test_rag_evaluation_set.py backend\tests\test_rag_evaluation.py -q
.\scripts\run-no-shop-demo.ps1 -SkipFrontend
~~~

Hai lệnh đầu không tương đương: evaluate_rag_set.py kiểm tra định tuyến xác định; evaluate_rag_quality.py đo định tuyến và truy xuất trên dữ liệu demo, hiện chưa gọi LLM. Muốn chấm câu trả lời sinh thật phải dùng tenant test, bộ fixture đóng băng và ngân sách AI được duyệt; không chạy 100 câu lên tài khoản khách thật.

## 5. Việc tiếp theo nên làm

1. Dùng docs/rag-evaluation-latest-report.json làm baseline có ghi rõ lexical fallback.
2. Bổ sung/chốt bộ fixture sản phẩm + chính sách đã duyệt; sửa các ca thiếu nguồn hoặc kỳ vọng chưa chính xác.
3. Đo lại retrieval với embedding/vector thật và so sánh cùng bộ câu; ưu tiên lỗi CSV/SKU trước khi thêm mô hình/reranker mới.
4. Khi retrieval đạt, chạy thử sinh đáp án trên tenant demo có hạn mức; chấm citation, giá, handoff và câu hỏi nhiều lượt.
5. Chỉ sau đó mở rộng CRM tools, RFM và từng adapter; mọi thay đổi phải giữ tenant isolation và chống gửi lặp.

RAG tốt không được đo bằng số lượng “mục kiến thức” hay số vòng suy luận. Được đo bằng việc bot lấy đúng sự thật của đúng shop, biết lúc nào cần hỏi lại/chuyển người, và không tạo hành động hoặc thông tin không có căn cứ.

## 6. Phần đã triển khai và kết quả thử nghiệm

Đợt triển khai ngày 12/10/2026 đã làm các phần sau trên dữ liệu demo, không bật dùng mô hình thử nghiệm cho shop thật:

- Tìm kiếm RAG kết hợp đã được bổ sung khớp SKU chính xác, từ khóa tiếng Việt không dấu/biến thể cách gọi, lọc đúng shop, giới hạn đoạn lặp từ cùng tài liệu và mở rộng ngữ cảnh cha có giới hạn.
- Prompt tách dữ liệu tài liệu khỏi chỉ thị hệ thống, giới hạn số sản phẩm đề xuất, cấm tự tạo liên kết và không khẳng định đã tạo đơn/nhận tiền nếu CRM chưa xác nhận. Cổng citation kiểm tra mã hàng, giá, liên kết và nhãn liên kết mẫu; nếu không đạt thì chuyển nhân viên thay vì gửi câu trả lời chưa kiểm chứng.
- Các câu hỏi giá, SKU, tồn kho, đơn của đúng khách/hội thoại được định tuyến sang đọc dữ liệu CRM có phạm vi `business_id`; dữ liệu cấu trúc không lấy từ đoạn RAG cũ. Bộ kiểm tra định tuyến xác định đạt 100/100, nhưng đây không phải phép đo độ đúng của mọi câu trả lời CRM trên từng mạng xã hội.
- Bộ checkpoint từ Data_RAG được xuất sang JSON suy luận portable và đặt trong thư mục artifact bị Git bỏ qua. Compose mount chỉ đọc vào backend/worker; chế độ mặc định không bật áp dụng cho shop. Giao diện thử nghiệm chỉ xếp lại tối đa ba ứng viên đã lọc theo catalog demo và xem phân cụm RFM, không ghi vào hồ sơ khách.
- Quy tắc RFM bỏ đơn chưa hoàn tất/đã hủy/thất bại, tính chi tiêu thuần theo hoàn tiền và để khách chưa có đơn ở nhóm riêng. Phần ghi nhớ hội thoại chỉ lấy dữ kiện gần đây, có kiểm tra nguồn/độ tin cậy/thời hạn và phạm vi đúng khách.

### Kết quả có thể tái lập

| Phép đo | Kết quả | Đánh giá |
|---|---:|---|
| Tìm kiếm hybrid trên lượt có ghi rõ chế độ | 39 câu có nguồn mong đợi; 10/40 câu gặp lỗi quota embedding và tự rơi về từ khóa. Trong 29 câu không fallback, Recall@5 đạt 95,65%, đủ nguồn top-5 đạt 93,10% | Nhóm hybrid đạt ngưỡng trên tập con, nhưng chưa có đủ 40/40 câu chạy vector để chấp nhận làm cổng phát hành. Toàn lượt pha trộn có Recall@5 85,25%. Báo cáo và danh sách câu fallback: `docs/data-rag-retrieval-diagnostic-report.json`. |
| Các lượt exact-scan trước khi thêm theo dõi fallback | Điểm Recall@5 biến động 78,69–95,08%; một lượt lặp lại bị quota chặn trước khi đo xong | Chưa thể coi đây là phép đo thuần vector vì những lượt này chưa ghi rõ câu nào fallback. Cùng một câu/tài liệu cho embedding trùng khớp cosine 1,0; nguyên nhân của mọi chênh lệch chưa được quy kết chắc chắn. Báo cáo phụ: `docs/data-rag-retrieval-exact-scan-report.json` và `docs/data-rag-retrieval-exact-repeat-report.json`. |
| LLM trên 39 câu có nguồn mong đợi | Sinh đủ 39 câu; citation gate 89,74%; cụm từ bắt buộc 25,40%; không có cụm từ cấm 94,87%; độ trễ trung bình 12,60 giây | Chưa đạt: cổng từ chối một số câu chưa gắn nguồn đủ chặt và phần lớn đáp án chưa khớp nguyên văn đáp án kiểm thử. Lượt này chưa ghi số ca fallback truy xuất nên chỉ dùng để chẩn đoán, không làm cổng phát hành. Citation chỉ xác minh một phần dữ kiện; câu bị từ chối phải chuyển nhân viên. |
| Xếp hạng sản phẩm trên tập test giữ lại 10.000 hội thoại | Hit@1: 59,10% so với 32,30% theo thứ tự gốc; Hit@2: 85,59% so với 66,97%; MRR@3: 0,7715 so với 0,6065 | Cải thiện trên nhãn tương tác thay thế, không phải chuyển đổi mua hàng/doanh thu. Chưa chứng minh tăng doanh số shop thật. |
| Phân cụm RFM | Khớp checkpoint portable 9.997/9.997 khách có đơn; 3 khách không có đơn vẫn ở nhóm khách mới | Xác nhận tương thích phép tính/mô hình trên tập tổng hợp; mã cụm chỉ là nhóm toán học, chưa phải nhãn VIP trung thành cho shop thật. |
| Tự kiểm tra backend | `scripts/run-no-shop-demo.ps1 -SkipFrontend`: 1.198 đạt, 2 bỏ qua; định tuyến 100/100 | Bộ frontend xem trước riêng đạt 1/1; `npm run build` đạt. Build còn cảnh báo bundle JavaScript lớn hơn 500 kB. |

Các báo cáo đánh giá model và RFM: `docs/data-rag-integration-report.json`. Kịch bản cài artifact: `scripts/install_data_rag_models.py`; đánh giá tập test: `scripts/evaluate_data_rag_integration.py`. Mô hình mới chỉ được dùng trong màn hình xem trước tổng hợp, không dùng làm nguồn sự thật hoặc tự động quyết định khách hàng thật.

### Chưa coi là hoàn tất để phát hành

1. Chạy lại đủ 40 câu khi embedding còn quota và yêu cầu không có bất kỳ fallback nào (`--require-full-vector`). Dù 29 ca vector thuần hiện đạt Recall@5 95,65%, chưa được thay bằng phép đo đủ bộ.
2. Đáp án tổng hợp chưa đạt kiểm tra cụm từ bắt buộc và có thể bị cổng citation từ chối; cần rà lại answer key, từng ca câu trả lời, sau đó mới mở trả lời tự động.
3. Chưa có chính sách, catalog, bảo hành/đổi trả và nội dung đã được chủ shop thật duyệt. Các file hiện tại là giả lập, tuyệt đối không nhập vào shop thật để bot trả lời khách.
4. Chưa chứng nhận gửi/nhận ảnh, giọng nói và độ ổn định end-to-end riêng trên cả sáu nền tảng. Cần kiểm tra từng adapter và các quyền/cửa sổ gửi của nhà cung cấp bằng tài khoản thử riêng.
5. Chưa chạy thử A/B hoặc đo tăng chuyển đổi/RFM trên dữ liệu shop thật có sự đồng ý. Không tự động bật mô hình dựa vào điểm tổng hợp này.

## 7. Đợt củng cố luồng dùng chung ngày 12/10/2026

Đã triển khai thêm các sửa đổi sau cho hỏi đáp nội bộ và luồng trả lời của sáu kênh:

- Embedding câu hỏi thành công được giữ trong bộ nhớ đệm tối đa 512 câu theo provider/model/dimension. Kết quả lỗi không được cache; đổi mô hình không dùng lại vector của mô hình cũ. Bộ đánh giá dùng `embed_queries` với task `RETRIEVAL_QUERY` theo lô và truyền vector đã kiểm tra vào cùng hàm truy xuất. Cùng 40 câu không còn cần 40 request embedding riêng.
- Nhật ký RAG ghi trực tiếp `retrieval_mode`, `retrieval_fallback_stage`, `retrieval_error_type` và số vector/từ khóa khớp. Bộ đánh giá đọc các trường này thay vì suy ra từ chuỗi cảnh báo.
- Câu ngắn hỏi thành phần, cách dùng, công suất, tương thích hoặc SKU không còn bị coi là hội thoại thông thường để bỏ qua kho kiến thức. Câu hỏi thuộc tính đi vào RAG; câu hỏi giá/tồn vẫn đọc CRM.
- Câu nối tiếp không nêu sản phẩm được bổ sung tên sản phẩm từ hội thoại hoặc các tin khách vừa gửi. Tên/SKU mới nhưng không khớp không được thay bằng sản phẩm đã hỏi trước. Khớp alias có ranh giới từ để `serum010` không bị hiểu là `serum01`.
- Khi RAG trả lời thuộc tính của một sản phẩm đã xác định, ngữ cảnh bổ sung bản ghi giá/tồn/mô tả hiện hành của đúng shop. Cổng đáp án từ chối số tiền cũ dù tài liệu cũ được trích dẫn; phản hồi lưu ID sản phẩm, giá/tồn và thời điểm đọc. Giá/tồn được lấy từ CRM, thông tin giải thích lấy từ tài liệu.
- Hỏi giá thiếu tên hàng được hỏi làm rõ; yêu cầu chuyển nhân viên hoặc dữ liệu khách khác được chặn trước LLM. Cả API thường và API stream có cùng hành vi này.
- Tìm từ khóa bỏ trọng số của từ phụ không xuất hiện trong kho nhưng vẫn giữ điều kiện về các khái niệm thương mại. `10-unit`/`2-pack`/`600-ml` không còn bị coi là SKU; “giải thích” không còn bị hiểu là sở thích khách. Kiểm tra bảng giá đọc đủ các dòng và không nối số tồn ở dòng trước vào giá ở dòng sau.

124 bài kiểm tra trọng tâm và 4 subtest đã đạt, trong đó có kiểm tra cùng ngữ cảnh/giá hiện hành trên Facebook, Instagram, Telegram, Zalo, TikTok và Shopee với bộ gửi giả lập. Kiểm tra thuật toán từ khóa chạy đủ 39 câu có nguồn trong 40 câu demo: Recall@5 68,85%, đủ tất cả nguồn 53,85%, bằng chứng 54,69%; định tuyến 100/100. Lệnh chấm retrieval vẫn trả trạng thái chưa đạt vì còn thiếu nguồn.

Toàn bộ backend no-shop sau sửa đạt **1.213 bài, 2 bỏ qua và 20 subtest**. Backend và worker local đã được khởi động lại bằng `scripts/docker-rag-runtime.override.yml`, chỉ chạy server khi còn backlog migration ngoài đợt RAG. `/health` trả `ok`, hai container healthy, artifact demo đọc đủ 2.000 sản phẩm; phiên bản schema shop không đổi và không còn schema `rag_eval_*`.

Lượt Gemini thật của đợt này bị quota chặn ngay khi tạo embedding tài liệu, trước khi tạo schema thử. Vì vậy chưa có số đo hybrid/LLM mới để thay báo cáo trước. Cần chạy lại lệnh strict trong `docs/rag-learning-operations.md` khi nhà cung cấp cho phép gọi; không suy diễn điểm truy xuất từ bộ unit test.

Các tình huống cần thử trong Trợ lý hỏi đáp: hỏi SKU có thật về giá; hỏi SKU đó về thành phần/công suất; hỏi nối tiếp “giá bao nhiêu?”; nhắc một SKU mới bị gõ sai; hỏi giá khi chưa nhắc sản phẩm; yêu cầu xem đơn của khách khác. Với hai tình huống cuối, kết quả phải là hỏi làm rõ hoặc chuyển nhân viên. Dùng tài liệu đã xác nhận của shop để chấm câu trả lời thuộc tính.

