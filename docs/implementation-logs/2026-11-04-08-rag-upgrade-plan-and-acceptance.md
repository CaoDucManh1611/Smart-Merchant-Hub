# RAG: kế hoạch nâng cấp và hợp đồng nghiệm thu

Ngày: 2026-11-04. Nhánh: `codex/rag-rfm-all-updates-20261104`.
Trạng thái: kế hoạch được người dùng chấp thuận; bản ghi này chưa chứng minh các nâng cấp đã triển khai.

## Phân công

- Agent chính: đối chiếu source, chuẩn bị thứ tự thay đổi và phép đo, tích hợp sửa đổi sau phản biện.
- Agent phụ Gibbs (`01a1a633-ffb6-7112-a257-0984fa57f006`): phản biện độc lập source và kế hoạch, ghi findings ở log 09. Agent phụ không thay source hoặc trạng thái dữ liệu.
- Dừng QA shop làm đẹp theo chỉ đạo mới. Không dùng các hội thoại test do agent tạo làm bằng chứng hành vi mua thật hoặc đưa tự động vào training.

## Thứ tự thực hiện

| Bước | Phạm vi | Điều kiện hoàn tất trước khi bật |
| --- | --- | --- |
| 1 | Chuẩn hóa giao diện gọi chung cho Graph và auto-reply; giữ workflow tạo đơn/thanh toán/đặt lịch và shortcut catalog hiện có | Cùng quyền, nguồn, hard filters, retrieval mode theo shop, timeout và kiểm tra nguồn; trace ghi rõ đường thực thi |
| 2 | Tìm catalog theo điều kiện cho hàng hóa, dịch vụ, cho thuê | Lọc shop/status/thuộc tính bắt buộc trước LIMIT; ưu tiên mã chính xác; tìm được mục ngoài 100 dòng đầu; phân trang khi khách hỏi toàn bộ; đọc lại dữ kiện hiện hành |
| 3 | Kiểm kê và reindex tài liệu có chunk lỗi | Dry-run thống kê theo shop, phân biệt catalog/policy/hướng dẫn, dự toán embedding; xây chỉ mục thay thế, kiểm tra mapping rồi đổi bản active; giữ đường rollback |
| 4 | Trạng thái hội thoại có cấu trúc | Lưu các ID vừa nêu, tập so sánh, ràng buộc khách xác nhận và slot đang thiếu; có reset/TTL; không lưu giá/kho như sự thật lâu dài |
| 5 | Output có schema cho planner/composer | Xác minh provider/model thực sự hỗ trợ; xác thực schema và quyền tool phía server; JSON hợp lệ vẫn phải kiểm tra ngữ nghĩa và nguồn |
| 6 | Retrieval thích ứng | BM25 baseline; hybrid/expansion chỉ khi cần và dưới cờ riêng; giữ nguyên hard filters; PPR ngoài serving; không coi similarity là xác suất đúng |
| 7 | Kiểm chứng claim | Giá/kho/SKU/tiền tính từ nguồn hiện hành; chính sách đúng phạm vi/hiệu lực; tương thích chỉ khi có bằng chứng; bỏ hoặc hỏi lại phần không chứng minh được |
| 8 | Học từ phản hồi | Lưu lỗi, trace nguồn, sửa của nhân viên, trạng thái duyệt; chỉ nội dung đã xác nhận mới vào KB/training; kiểm tra consent và tenant |

## Giới hạn độ trễ và lượt gọi

- Câu catalog đủ điều kiện: SQL và dựng câu trả lời trực tiếp, không bắt buộc gọi LLM.
- Câu tư vấn/tổng hợp thông thường: mục tiêu một lượt sinh câu trả lời; planner chỉ gọi model khi router hiện có không đủ chắc chắn.
- Retry, query expansion, reranker, verifier và provider fallback phải chia sẻ deadline tổng và ngân sách của lượt chat. Không cộng lại toàn bộ timeout ở từng nhánh.
- Giữ retry sửa lỗi có giới hạn; không cho nhiều tầng retry nhân số lượt gọi. Log cả lượt lỗi 429, thời gian chờ và fallback, không ghi khóa/API credentials.
- Khi provider hết ngân sách/deadline: trả phần đã xác minh hoặc hỏi lại/chuyển nhân viên. Không xác nhận tác vụ giao dịch khi chưa có kết quả commit.
- Ngưỡng số cụ thể về p95/chi phí phải được chốt từ baseline trước khi chạy so sánh; không tự coi ngưỡng chưa đo là đã đạt.

## Bảy tiêu chí nghiệm thu

| Tiêu chí | Cách kiểm tra | Trạng thái của đợt nâng cấp |
| --- | --- | --- |
| Nhất quán các kênh | Replay cùng nội dung và cùng context chuẩn hóa qua các adapter; đối chiếu hành vi, sản phẩm, con số và nguồn, không bắt câu chữ giống hệt | Chưa chạy |
| Không hụt catalog sau dòng 100 | Fixture >100 mục mỗi loại, mục đúng ở cuối; query có điều kiện và query yêu cầu toàn bộ | Chưa chạy |
| Không trộn shop/SKU/biến thể | Hai tenant có tên/mã tương tự; negative cases sai size, trạng thái, tương thích; kiểm tra cả candidate lẫn kết quả hiển thị | Chưa chạy |
| Hiểu câu nối tiếp | Cặp so sánh → rẻ hơn; đổi chủ đề → quên tập cũ; sửa ngân sách → thay điều kiện; placeholder → hỏi lại | Chưa chạy đầy đủ |
| Thiếu bằng chứng hỏi đúng phần thiếu | Có tên/giá nhưng chưa xác minh tương thích: trả phần biết, chỉ hỏi phần thiếu; không đoán | Chưa chạy đầy đủ |
| 429 fallback an toàn | Mô phỏng 429, timeout, fallback cũng lỗi; kiểm tra tổng lượt gọi, deadline và không lặp ghi giao dịch | Chưa chạy |
| Có phép đo trước/sau | Cùng snapshot, case, prompt/model/config; báo quality, latency, tokens/cost, fallback theo shop/nhóm câu | Chưa có baseline chung cho nâng cấp này |

## Hợp đồng phép đo

Mỗi run giữ cố định catalog/document snapshot, consent scope, phiên bản code, model/prompt và cấu hình. Mỗi turn cần ghi:

- `run_id`, `case_id`, `business_id`, `conversation_id`, `channel`, `code_version`, `config_version`.
- Intent/tool/route thực tế; nguồn/ràng buộc đã chọn; lý do hỏi lại hoặc fallback.
- Trạng thái memory trước/sau và lý do reset (ẩn dữ liệu cá nhân trong báo cáo chia sẻ).
- Catalog IDs và document ID + revision/hash, mode retrieval, số ứng viên, ID thực sự hiển thị.
- Thời gian từng bước và đầu cuối; số call theo provider/model, token input/output, cache, chi phí ước tính với phiên bản bảng giá. Provider không trả token thì ghi unknown, không ghi 0.
- Câu trả lời, lỗi cứng, tính hữu ích, hỏi lại đúng lúc và provenance của nhãn (`ai_proposed`, `human_confirmed`, `rule_checked`). Nhãn AI không tự đổi thành nhãn người.

So sánh ghép cặp theo case, theo shop và nhóm câu: catalog, policy, tư vấn, nhiều ý, nối tiếp, giao dịch, thiếu dữ liệu. Báo p50/p95, tỷ lệ fallback và tỷ lệ trả lời hữu ích; tách lỗi nguồn/routing/sinh câu. Chi phí và thời gian phải tính cả retry/fallback.

Lỗi chặn bật: rò tenant, sai giá/tổng tiền, khẳng định tồn kho hoặc tương thích không có bằng chứng, thực hiện giao dịch sai. Không dùng việc tăng từ chối để giả cải thiện độ đúng. Shadow/canary theo shop sau khi đạt gate; giữ baseline để rollback.

## Ca nghiệm thu nhiều điều kiện từ người dùng

Đầu vào: “Xe Vision 2023 của mình cần thay nhớt, dưới 200k có loại nào phù hợp? Nếu mua 2 chai thì bao nhiêu?”

- Trích đúng nhu cầu nhớt động cơ, xe Vision, năm 2023, ngân sách 200.000 VND và số lượng hai chai. Không khớp nhầm nhớt hộp số chỉ vì tên cùng có “xe tay ga”.
- Giữ rõ phạm vi ngân sách theo món/tổng; nếu cách hiểu làm thay đổi lựa chọn mà câu chưa rõ, hỏi đúng phần đó.
- Candidate phải thuộc shop hiện tại, trạng thái đang bán và đúng thuộc tính có nguồn. Tương thích chưa biết phải giữ trạng thái unknown; không suy ra năm xe từ tên sản phẩm hoặc biến unknown thành compatible.
- Lấy giá và tồn khả dụng hiện hành, kiểm tra đủ hai chai. Tiền cho hai chai do server tính từ giá có nguồn, không dựa vào phép tính tự sinh không kiểm chứng.
- Nếu thiếu bằng chứng tương thích/dung tích, có thể nêu sản phẩm và giá đã xác minh, đồng thời hỏi hoặc nhờ kiểm tra đúng thông tin còn thiếu; không hứa chắc chắn dùng vừa và không tự tạo đơn.
- Replay với tên xe khác, ngành khác, số lượng khác và giá cập nhật để kiểm tra đây là năng lực xử lý nhiều điều kiện, không phải một câu trả lời hard-code.

## Tiếp nhận phản biện độc lập

Agent Gibbs đã hoàn tất log 09 với năm findings. Agent chính đã đọc log và đối chiếu lại các đoạn ingestion/catalog sync, quota worker và xác thực offering trong workflow.

- Chấp nhận P0 reindex: đường ingestion hiện gọi sync catalog, có thể ghi lại giá/kho/status cũ với sản phẩm do cùng tài liệu quản lý. Bước 3 chỉ được chạy sau khi tách rõ reindex-only với cập nhật dữ liệu đang bán và kiểm tra bất biến catalog.
- Chấp nhận rủi ro publish/quota: worker xử lý quota tăng thêm sau ingestion, có nhánh xóa chunks khi vượt quota. Gate phải giữ cả chỉ mục đang phục vụ và dữ liệu catalog, không chỉ bảo đảm transaction insert chunks.
- Chấp nhận phạm vi LIMIT 100: sửa bước 2 phải phủ exact offering-ref trong workflow, không chỉ giảm prompt catalog. Giữ tenant/row lock/kiểm tra khả dụng và xác nhận hiện có.
- Chấp nhận thiếu budget chung: bước 1 cần truyền deadline/call budget vào mọi nhánh. Số attempts nêu trong log 09 là phân tích trần từ source, chưa phải số đo thực tế.
- Chấp nhận rủi ro tập so sánh theo kích thước: cùng size không đủ nhận diện đúng SKU/biến thể. Bước 4 lưu tập ID thực sự hiển thị; nếu chưa có tập đáng tin thì hỏi lại.

Các findings chưa được sửa trong lượt lập kế hoạch/đánh giá này. Không gate nào được nâng thành runtime PASS từ review tĩnh. Phiên bản kế hoạch sau phản biện vẫn giữ thứ tự tám bước, bổ sung các điều kiện chặn trên.

## Giới hạn của bản ghi

Bản này là kế hoạch và tiêu chí; chưa chạy migration, reindex, benchmark hoặc xác minh tính năng provider. Các điểm benchmark/model trong tài liệu đầu vào là kết quả báo cáo tĩnh, không phải kết quả runtime mới. Source đang có thay đổi chưa commit; cần lưu revision/diff fingerprint của snapshot thực tế khi đo.
