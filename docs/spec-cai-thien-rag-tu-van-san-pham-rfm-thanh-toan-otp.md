# Spec cải thiện RAG, tư vấn sản phẩm, RFM, chuyển khoản và email OTP

**Trạng thái:** Đã triển khai một phần; các tích hợp bên ngoài và cổng chất lượng production còn mở · **Phạm vi:** RAG/CRM, tư vấn và gợi ý sản phẩm, nhãn RFM, thông tin nhận chuyển khoản, email mã xác minh.

## 1. Mục tiêu

Làm cho câu trả lời và thao tác của Smart Merchant Hub đúng nguồn, có thể đo được, không rò dữ liệu giữa các shop và không báo thành công khi hệ thống mới chỉ gửi yêu cầu đi. Mỗi nhóm tính năng phải có dữ liệu kiểm thử, tiêu chí nghiệm thu, theo dõi vận hành và cách xử lý khi thiếu dữ liệu hoặc nhà cung cấp gặp lỗi.

Nguyên tắc dùng chung:

- Database/API CRM là nguồn chuẩn cho khách hàng, deal, đơn hàng, giá, tồn kho, trạng thái thanh toán và cấu hình shop. RAG phục vụ nội dung cần diễn giải như ghi chú, email, chính sách và tài liệu sản phẩm đã duyệt.
- Áp dụng tenant, quyền người dùng và bộ lọc nghiệp vụ trước khi truy xuất hoặc xếp hạng dữ liệu. Không đưa dữ liệu ngoài phạm vi được phép vào prompt.
- Mọi kết luận quan trọng phải truy ngược được tới bản ghi, tài liệu hoặc phản hồi của nhà cung cấp. Thiếu căn cứ thì hỏi lại, nói chưa đủ dữ liệu hoặc chuyển nhân viên.
- Không ghi OTP, mật khẩu SMTP, khóa webhook, số tài khoản đầy đủ hoặc nội dung nhạy cảm vào log. Cá nhân hóa theo lịch sử chỉ bật khi có consent hợp lệ.
- LLM không tự xác nhận tiền đã vào, không sửa trạng thái thanh toán và không được biến nội dung khách gửi thành sự thật của CRM.

## 2. Hiện trạng và khoảng trống

| Khu vực | Đã có trong code | Khoảng trống cần xử lý |
|---|---|---|
| RAG và CRM | Hybrid vector/từ khóa, chia đoạn theo cấu trúc, guard/citation, route một số câu CRM sang truy vấn dữ liệu có cấu trúc, log chi phí và nguồn. Bộ đánh giá CRM mới có 13 ca tổng hợp; kết quả route/nguồn/hành động đạt 100% và MRR 1.0 trên bộ đó. | Chưa coi kết quả demo/SQLite là bằng chứng cho lưu lượng thật. Cần một bộ chuẩn phủ đồng thời retrieval vector, LLM, quyền, câu hỏi mơ hồ, dữ liệu cũ và no-answer; theo dõi chi phí/độ trễ theo provider và tenant test. Các lần đánh giá RAG gần đây cũng ghi nhận quota làm một phần lượt vector fallback, nên chưa có cổng chất lượng hybrid đầy đủ. |
| Tư vấn sản phẩm | Tra cứu SKU/tên, đọc catalog hiện hành cho giá/tồn, có tư vấn dựa trên RAG, so sánh catalog và đối chiếu ảnh sản phẩm. | Cần đánh giá độc lập tính đúng của thông tin catalog, bằng chứng cho thuộc tính/tương thích, xử lý biến thể thiếu rõ ràng và khả năng hỏi lại khi nhu cầu chưa đủ cụ thể. |
| Gợi ý sản phẩm | Pipeline có candidate catalog/RAG, lọc tenant/sản phẩm đang bán/còn hàng/sản phẩm vừa mua; có tín hiệu mua chung, tương tác, truy vấn và RFM; cá nhân hóa cần consent; có lưu feedback. | Chưa có bộ ranking chuẩn theo từng intent/nhóm khách và cổng A/B có guardrail. Cần đo chất lượng gợi ý, độ phủ, đa dạng, cold-start và chuyển đổi; kiểm tra lý do gợi ý có đúng bằng chứng. |
| RFM và nhãn | Endpoint Customer CRM đã có percentile score và nhãn nghiệp vụ tiếng Việt. Worker profile cá nhân hóa cũng tính R/F/M và giữ `as_of`. | Worker trước đây ghi `rfm_cluster_N` và tạo tag “AI nhóm N”, không dùng chung nhãn CRM. Cần hợp nhất taxonomy, lưu score/rule version và không trình bày cluster ID như nhãn khách hàng. |
| Nhận chuyển khoản | Cấu hình ngân hàng/số tài khoản/tên người nhận theo shop; mã hóa số tài khoản; kiểm tra định dạng và tạo VietQR. Có webhook MONA Pay xác thực chữ ký, chống phát lại theo thời gian và ghi giao dịch idempotent. | Danh sách BIN/định dạng hợp lệ chưa xác minh tài khoản có thật hoặc chủ tài khoản. Giao dịch webhook hiện được lưu như bản ghi nhận vào, chưa đủ để kết luận đã đối soát đúng shop/đơn. Cần phân biệt rõ trạng thái kiểm tra cấu hình, xác minh người nhận và xác nhận thanh toán. |
| Email OTP | SMTP platform có endpoint gửi thử và cooldown; SMTP riêng của shop được mã hóa cấu hình và dùng trong luồng OTP. | Platform test trước đây gửi mã OTP rời không có bước verify; shop chưa có endpoint gửi thử riêng. Cần email probe không chứa OTP, cooldown riêng theo shop, và diễn đạt chính xác rằng SMTP accept chưa xác nhận Inbox. |

## 3. Spec theo nhóm chức năng

### 3.1. RAG và truy vấn CRM

**Phân tuyến dữ liệu**

- Câu hỏi về số lượng deal, giai đoạn, owner, ngày, khách theo ID/tên và lịch sử CRM phải gọi tool/database có schema cố định. Không để LLM tự viết hoặc thực thi SQL tùy ý.
- Câu hỏi về ghi chú, email, hội thoại và tài liệu chính sách dùng RAG. Khi câu hỏi cần cả hai loại dữ liệu, lấy record CRM làm fact hiện hành và RAG làm bằng chứng diễn giải.
- Giá, tồn, đơn, thanh toán và trạng thái vận chuyển luôn đọc live từ CRM/provider. RAG không được ghi đè các giá trị này bằng tài liệu cũ.

**Metadata và bảo mật truy xuất**

Mỗi chunk cần giữ tối thiểu: `tenant_id/business_id`, `document_id`, `source_kind`, `source_record_id`, `customer_id`/`deal_id` nếu có, `owner_id` hoặc ACL, `created_at`, `updated_at`, `source_version`, `chunker_version`, `embedding_model` và URI điều hướng nội bộ. Giữ các ID gốc xuyên suốt retrieval → prompt → citation → log đánh giá.

Truy vấn tên/mã dùng tìm kiếm lexical chính xác hoặc chuẩn hóa có kiểm soát; truy vấn ngữ nghĩa dùng vector; hybrid được đo với cùng fixture. Lọc tenant/quyền/owner/trạng thái/ngày trước khi đưa chunk vào câu trả lời. Nếu hai nguồn mâu thuẫn, ưu tiên nguồn có thẩm quyền và mới hơn theo loại dữ liệu; nếu không xác định được thì nêu mâu thuẫn hoặc chuyển nhân viên.

**Trả lời và nguồn**

- Citation phải trỏ tới record/tài liệu thật, gồm loại nguồn và thời điểm cập nhật phù hợp. Không tạo đường dẫn, tên khách hoặc ID không có trong kết quả.
- Câu hỏi không có dữ liệu phải trả lời rõ chưa tìm thấy trong phạm vi đã kiểm tra; không lấp chỗ trống bằng kiến thức chung hoặc suy đoán về khách hàng.
- Lưu `retrieval_mode`, fallback stage/reason, IDs nguồn, latency từng bước, token/cost ước tính và kết quả guard. Không lưu bí mật hay toàn bộ PII không cần thiết.

**Bộ eval bắt buộc**

Tạo bộ có answer key và source IDs cho: khách theo tên/ID; lịch sử trao đổi theo khách; lọc deal theo stage/owner/khoảng ngày; câu có từ đồng nghĩa/lỗi gõ; tên trùng; tenant khác; tài liệu mới/cũ mâu thuẫn; câu không có bằng chứng; câu cần CRM + RAG. Chạy tách ba chế độ lexical, vector và hybrid; thêm lượt LLM trên fixture cố định để chấm độ đúng câu trả lời, citation và abstention.

### 3.2. Tư vấn sản phẩm và gợi ý sản phẩm

Phân biệt hai hành vi trong route và log:

- **Tư vấn:** trả lời câu hỏi về sản phẩm hoặc so sánh dựa trên thuộc tính catalog đã xác nhận và tài liệu sản phẩm đã duyệt; nói rõ ưu/nhược điểm, điều kiện tương thích và điểm chưa chắc.
- **Gợi ý:** xếp hạng mặt hàng phù hợp nhu cầu hiện tại; chỉ dùng hồ sơ/tương tác mua hàng nếu khách đã đồng ý cá nhân hóa. Mỗi gợi ý nêu lý do ngắn dựa trên tín hiệu cụ thể, không gắn nhãn “phù hợp nhất” khi không có căn cứ.

Yêu cầu:

- SKU, biến thể, giá, tồn khả dụng và trạng thái bán lấy từ catalog hiện hành của đúng tenant. Giá/tồn phải gắn thời điểm đọc trong trace; không dùng con số trong chunk cũ.
- Mô tả, cách dùng, chất liệu, bảo hành và tương thích chỉ lấy từ trường catalog có cấu trúc hoặc tài liệu có nguồn. Khi thuộc tính chưa được cung cấp, nói chưa có thông tin.
- Nếu khách chưa nói ngân sách, mục đích, kích cỡ hoặc tiêu chí cần thiết để phân biệt sản phẩm, hỏi một câu làm rõ trước khi xếp hạng. Không tự suy ra đặc điểm nhạy cảm.
- Candidate phải loại sản phẩm sai tenant, ngừng bán, hết hàng và sản phẩm khách vừa mua theo quy tắc đã công bố. Cold-start dùng sản phẩm phổ biến/đang có hàng trong ngành hàng phù hợp, không giả vờ đã cá nhân hóa.
- Feedback hiển thị/gợi ý phải idempotent; `view`, `click`, `cart`, `purchase`, `skip`, `refund` được ghi đúng sự kiện. Không tính click là chuyển đổi.
- Có bộ so sánh theo nhóm nhu cầu, exact SKU/variant, câu hỏi giá/tồn, yêu cầu không tồn tại, cold-start, có/không consent và phản hồi ảnh không đủ rõ.

### 3.3. RFM và nhãn khách hàng

**Định nghĩa dữ liệu đề xuất**

- `R`: số ngày từ đơn đủ điều kiện gần nhất đến `as_of`.
- `F`: số đơn đủ điều kiện trong cửa sổ phân tích.
- `M`: doanh thu thuần trong cửa sổ, trừ hủy/hoàn/hoàn tiền theo trạng thái đơn chuẩn của hệ thống.
- Đơn đủ điều kiện phải thống nhất với trạng thái “completed hoặc paid-delivered” hiện có. Đơn thử nghiệm, đơn hủy và giao dịch chưa thanh toán không được tính.
- Đề xuất mặc định cửa sổ 365 ngày để phân khúc hành vi gần đây; giữ thêm lifetime aggregates để nhân viên xem lịch sử dài hạn. Nếu nghiệp vụ muốn all-time, quyết định này phải được cấu hình và ghi trong profile/report.

**Nhãn và giải thích**

- Không trình bày `cluster_id` hoặc thứ hạng cluster như nhãn kinh doanh. Lưu `cluster_id`, `model_version`, `as_of` cho phân tích; map sang nhãn ổn định có định nghĩa rõ, ví dụ “Mới”, “Đang hoạt động”, “Trung thành”, “Có nguy cơ rời bỏ”, “Giá trị cao”.
- Mapping phải dựa vào ngưỡng/đặc trưng RFM được tài liệu hóa, được kiểm tra trên phân phối của từng shop và không gọi khách là VIP chỉ vì cluster xếp hạng cao. Có nhãn “Chưa đủ dữ liệu” cho khách chưa có đơn hoặc mẫu quá nhỏ.
- Mỗi nhãn hiển thị 2–3 lý do có thể kiểm chứng, như “mua 4 đơn trong 365 ngày”, “lần mua gần nhất 18 ngày trước”. Hiển thị ngày cập nhật và kỳ tính.
- Nhãn do RFM quản lý phải tách khỏi tag nhân viên tự tạo; job không xóa/sửa tag thủ công. Cho phép tắt phân khúc và personalization theo consent.
- Recompute theo lịch định kỳ và sau import/backfill; job có trạng thái, số khách/đơn, lỗi dữ liệu, phiên bản rule và khả năng chạy lại an toàn.

### 3.4. Tự động kiểm tra thông tin nhận chuyển khoản

Tách thành ba cấp kiểm tra; UI phải cho biết cấp nào đã đạt:

1. **Định dạng:** ngân hàng/BIN trong danh mục, số tài khoản hợp lệ về ký tự/độ dài theo ngân hàng khi có quy tắc, tên người nhận hợp lệ. Kết quả chỉ là `format_valid`.
2. **QR:** sinh QR/VietQR với đúng ngân hàng, người nhận, số tiền và nội dung chuyển khoản; giải mã fixture/QR trả về để đối chiếu từng trường. Kết quả `qr_validated` không chứng minh tài khoản tồn tại.
3. **Xác minh ngân hàng/người nhận:** chỉ trả `beneficiary_verified` khi một API/provider ngân hàng được ủy quyền trả kết quả xác thực tên–số tài khoản. Ghi provider, thời gian và mã tham chiếu; nếu không tích hợp được, để trạng thái “Chưa xác minh tại ngân hàng”, không nâng cấp từ bước 1 hoặc 2.

**Đối soát tiền vào**

- Chuẩn hóa giao dịch từ webhook/provider vào ledger, giữ tenant/provider/account đích, mã giao dịch duy nhất, số tiền, ngày, nội dung chuyển khoản, môi trường sandbox/live và thời điểm nhận. Không persist số tài khoản nguồn nếu không cần.
- Xác thực chữ ký trên raw body, timestamp/nonce, giới hạn kích thước, chống replay, idempotency và phát hiện transaction code bị tái sử dụng với payload khác. Giao dịch sandbox/test không được dùng để đánh dấu đơn thật đã thanh toán.
- Match theo tài khoản nhận + reference đơn + currency + amount + trạng thái đơn. Giao dịch thiếu reference, sai tiền, trùng, chuyển thiếu/thừa hoặc nhiều đơn cùng khớp phải vào hàng chờ đối soát thủ công.
- Chỉ backend reconciliation service/provider được phép chuyển đơn sang paid; không dùng LLM, ảnh biên lai hoặc lời khách làm xác nhận. Ghi audit actor=`system/provider`, nguồn sự kiện và khóa idempotency.
- MONA Pay webhook hiện tại xác thực và lưu transaction idempotent; nghiệm thu phần mở rộng phải chứng minh mapping tới đúng shop/đơn và lifecycle, không chỉ endpoint trả HTTP 200.

### 3.5. Email gửi mã xác minh

- Phân biệt cấu hình **sender platform** (đăng ký tài khoản) và **sender riêng của shop** (luồng dành cho shop đã tồn tại). Không fallback âm thầm sang sender khác trong production.
- Thêm kiểm tra gửi thử cho cấu hình shop với quyền owner/admin, recipient hợp lệ, cooldown/rate limit theo shop và actor; test gửi dùng cấu hình đã lưu, không dùng form chưa lưu.
- Theo dõi trạng thái tuần tự: `not_configured` → `config_saved` → `smtp_accepted` → `delivery_confirmed` (chỉ khi provider có receipt/webhook) → `otp_verified`. Lỗi phải có mã nguyên nhân an toàn và hướng dẫn; SMTP accept không được gọi là “đã vào Inbox”.
- Kiểm tra end-to-end bằng inbox sink/test mailbox: yêu cầu mã, nhận thư, xác minh đúng mã, từ chối mã sai/hết hạn, giới hạn resend và rate limit. Production probe không ghi OTP vào log; dùng provider delivery/bounce event hoặc mailbox test có kiểm soát để xác nhận thư đến.
- Bảo vệ SMTP credentials mã hóa khi lưu; không trả lại password qua API; không log OTP, nội dung email đầy đủ hoặc recipient không cần thiết. Ghi kết quả test theo run ID, provider, thời gian và trạng thái đã khử nhạy cảm.
- Theo dõi riêng platform/shop: tỷ lệ SMTP accept, delivery/bounce nếu có, OTP verify success, lỗi theo provider, p95 send latency và resend/rate-limit. Cảnh báo khi gửi lỗi liên tục hoặc không có delivery receipt trong ngưỡng.

## 4. Bộ đo và ngưỡng nghiệm thu đề xuất

Các ngưỡng dưới đây là đề xuất khởi điểm; chốt lại sau khi đo baseline trên fixture đại diện, không thay bằng kết quả unit test đơn lẻ.

| Nhóm | Đo lường | Cổng phát hành đề xuất |
|---|---|---|
| RAG | Recall@5, MRR/nDCG, grounded answer accuracy, citation validity, abstention precision/recall, cross-tenant leaks, p50/p95 latency, token và chi phí/câu. | 0 rò tenant; 100% nguồn/citation tồn tại; 100% truy vấn ID exact trong fixture; Recall@5 ≥ 0.90 trên bộ có nguồn; câu thiếu nguồn không khẳng định fact; p95/cost nằm trong ngân sách đã thống nhất. |
| Tư vấn sản phẩm | Đúng SKU/biến thể, đúng giá/tồn, độ đúng thuộc tính/tương thích, citation coverage, tỷ lệ hỏi lại/handoff. | 100% giá/tồn khớp fixture live; 0 mặt hàng sai tenant/đã ngừng bán; ≥ 95% fact tư vấn có bằng chứng; không suy đoán thuộc tính còn thiếu. |
| Gợi ý | Precision/Recall@K hoặc NDCG@K trên đánh giá có nhãn, hit rate, catalog coverage, diversity, stock eligibility, click/cart/purchase, skip/refund, latency. | 100% gợi ý thuộc catalog đủ điều kiện; 0 hết hàng; mọi lý do có feature/source; triển khai online qua A/B có nhóm đối chứng và guardrail trước khi mặc định bật. |
| RFM | Tính lặp lại cùng input/as-of, đối chiếu đơn/hoàn, tỷ lệ “chưa đủ dữ liệu”, kích thước nhóm, độ ổn định nhãn và freshness. | Kết quả R/F/M khớp bộ fixture 100%; profile có as-of/version; không ghi đè tag thủ công; nhãn mới/cluster có giải thích và không phụ thuộc tên cluster kỹ thuật. |
| Chuyển khoản | Tỷ lệ validate QR đúng, signature/replay/idempotency, tỷ lệ match đúng, unmatched/exception queue, thời gian nhận webhook. | 0 giao dịch giả/sandbox được ghi paid; 0 double-apply; 100% giao dịch đúng fixture map đúng đơn; thông tin chưa được provider xác minh không hiện “đã xác minh”; lỗi match đi review. |
| OTP email | SMTP acceptance, delivery/bounce khi provider hỗ trợ, OTP verify E2E, mã sai/hết hạn, resend/rate-limit, p95 send latency và secret leakage scan. | E2E pass trên platform và shop test sender; không báo “đã nhận” khi chỉ SMTP accept; mã sai/hết hạn luôn bị từ chối; 0 OTP/credential trong log hoặc API response. |

Mọi báo cáo cần lưu phiên bản code, fixture, tenant test, model/provider, cấu hình retrieval, thời điểm, số lượt fallback và trạng thái quota. Tách chỉ số demo, staging và production; không trộn chúng thành một điểm tổng.

## 5. Trình tự triển khai

### P0 — Chốt đo lường và chặn báo thành công sai

1. Đóng băng bộ eval hiện có; bổ sung answer key/source IDs cho RAG, tư vấn, gợi ý, RFM, OTP và thanh toán.
2. Bổ sung trace thống nhất và dashboard theo từng chế độ RAG/provider, latency, fallback, token/cost, error rate.
3. Hiển thị chính xác trạng thái email và chuyển khoản; viết kiểm thử chống `SMTP accepted = inbox received` và `QR valid = account/payment verified`.
4. Chạy smoke test cho webhook sandbox và luồng OTP bằng fake SMTP/inbox sink; không chạm tài khoản thật trong CI.

**Hoàn thành P0 khi:** eval chạy lặp lại được; có baseline; các trạng thái trung gian hiển thị đúng; test chứng minh không có cross-tenant retrieval, false paid hoặc false email-delivered.

### P1 — Chất lượng RAG, tư vấn và gợi ý

1. Đo lexical/vector/hybrid trên cùng bộ fixture; khắc phục quota/fallback và tăng đủ lượt vector trước khi chọn cấu hình mặc định.
2. Hoàn thiện metadata/citation ID và bộ lọc quyền; thêm test nguồn cũ, tên trùng, hỏi không có dữ liệu và CRM+RAG.
3. Tách route tư vấn khỏi recommendation ranking; chuẩn hóa fact catalog, biến thể, giá/tồn, và hỏi lại khi thiếu tiêu chí.
4. Đánh giá recommendation offline; kiểm tra consent, eligibility, cold-start, lý do gợi ý; sau đó chạy A/B nhỏ với rollback.

**Hoàn thành P1 khi:** đạt cổng đo tại mục 4 trên bộ eval đã duyệt và có report so sánh baseline/candidate; chưa đạt thì giữ route/cấu hình hiện tại hoặc handoff.

### P2 — Nhãn RFM và tích hợp vận hành

1. Chốt cửa sổ RFM, định nghĩa đơn/hoàn và ngưỡng nhãn với chủ sản phẩm/nghiệp vụ.
2. Tạo business labels có định nghĩa, giải thích và freshness; giữ cluster ID kỹ thuật ở lớp phân tích.
3. Thêm test gửi SMTP riêng cho shop và end-to-end inbox/OTP verification; triển khai delivery webhook/probe nếu provider hỗ trợ.
4. Nếu có provider xác minh tài khoản/nhận biến động số dư được ủy quyền, tích hợp qua adapter có sandbox, chữ ký, idempotency, health check và reconciliation queue. Nếu chưa có, giữ rõ trạng thái chưa xác minh/đối soát thủ công.

**Hoàn thành P2 khi:** dashboard vận hành cho từng shop thể hiện lần cập nhật RFM, trạng thái email, trạng thái kiểm tra tài khoản, sức khỏe webhook và giao dịch chờ xử lý; runbook có cách xử lý lỗi và replay an toàn.

## 6. Quyết định nghiệp vụ cần chốt trước khi bật production

1. RFM dùng cửa sổ 365 ngày hay all-time; đơn nào được tính và cách phân bổ hoàn tiền một phần.
2. Định nghĩa nhãn “Trung thành”, “Có nguy cơ rời bỏ”, “Giá trị cao” và ngưỡng tối thiểu số khách để tạo phân khúc.
3. Provider nào được phép xác minh tên chủ tài khoản/biến động số dư; webhook MONA Pay có cung cấp định danh tài khoản nhận và reference đủ để đối soát từng shop hay cần thêm API.
4. Shop có được cấu hình SMTP riêng hay dùng sender nền tảng; nhà cung cấp nào phát delivery/bounce receipt.
5. Ngân sách p95 latency và chi phí AI mỗi câu; mục tiêu conversion/guardrail cho thử nghiệm recommendation.

## 7. Tài liệu và mã hiện có

- [Lộ trình RAG CRM đa nền tảng](lo-trinh-rag-thong-minh-crm-da-nen-tang.md)
- [Vận hành gợi ý và RFM](recommendation-operations.md)
- [Cấu hình và kiểm thử OTP đăng ký](signup-email-setup.md)
- [Bộ đánh giá RAG CRM](crm-rag-evaluation.md)
- Service gợi ý: `backend/app/services/recommendation_service.py`
- Tư vấn sản phẩm: `backend/app/services/auto_reply_service.py`
- Chuyển khoản shop: `backend/app/services/shop_bank_transfer.py`; webhook: `backend/app/services/monapay_webhook_service.py`
- SMTP shop/platform: `backend/app/services/shop_otp_email.py`, `backend/app/services/platform_otp_email.py`, `backend/app/services/otp_delivery.py`

## 8. Trạng thái triển khai sau khi áp dụng spec

- RAG/CRM hybrid retrieval, truy vấn CRM có cấu trúc, citations, guard và bộ đánh giá hiện có được giữ làm nền; kết quả demo/fixture vẫn không được hiểu là số đo production.
- RFM profile worker và CRM dùng chung percentile scoring/nhóm nghiệp vụ. Profile recommendation lưu nhãn ổn định (`high_value`, `loyal`, `potential`, `needs_attention`, `at_risk`, `regular`, `new_customer`, `no_purchase`), nhãn hiển thị, score R/F/M, `as_of` và phiên bản rule. `cluster_id` còn lại chỉ là metadata phân tích; worker không tạo tag “AI nhóm N”.
- Ranker dùng segment RFM đã lưu để điều chỉnh nhẹ trọng số affinity/popularity/RAG/query theo từng chiến lược, chỉ khi khách có consent cá nhân hóa; trọng số hiệu lực và phiên bản rule được ghi vào context lần gợi ý. Tín hiệu mua cùng sản phẩm vẫn lấy từ đơn hàng tenant; mô hình NCF/LinUCB công khai còn ở chế độ demo, chưa phải model huấn luyện riêng theo đơn hàng production của shop.
- Chatbot liệt kê lý do gợi ý từ tín hiệu sẵn có, bên cạnh giá/tồn đọc live từ catalog.
- `POST /workspace/bank-transfer/validate` kiểm tra định dạng và round-trip trường VietQR/CRC bằng fixture nội bộ, trả rõ `beneficiary_verified: false`. Chưa có API ngân hàng để xác minh tên chủ tài khoản; endpoint không đánh dấu giao dịch đã trả tiền.
- `POST /workspace/otp-email/test` gửi email thử theo cấu hình đã lưu, có cooldown 60 giây theo shop và quyền owner/admin. Platform và shop cùng dùng email probe không chứa mã OTP; phản hồi là `smtp_accepted`, không phải xác nhận vào Inbox. Xác minh mailbox thật cần mailbox test hoặc delivery receipt từ provider.
- Chưa thể nghiệm thu toàn bộ spec production: xác minh chủ tài khoản/đối soát giao dịch cần provider ngân hàng được ủy quyền; xác nhận email đến cần mailbox hoặc delivery receipt; chất lượng gợi ý cần bộ xếp hạng có nhãn và A/B; điểm số RAG hiện có là fixture/demo và không đại diện traffic thật.
