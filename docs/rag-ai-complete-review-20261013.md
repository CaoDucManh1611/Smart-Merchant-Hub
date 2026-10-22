# Đánh giá AI thật hoàn tất — 13/10/2026

Đã chạy đủ 10 tình huống độc lập bằng embedding Gemini và mô hình Groq đang cấu hình. Đã tạo lại 167 embedding tài liệu và 10 embedding câu hỏi, truy xuất vector trong schema tạm được rollback. Lần chạy mới không có lỗi quota và không rơi về tìm từ khóa.

| Tiêu chí | Kết quả |
|---|---|
| AI thật sinh phản hồi trong lượt vector mới | 10/10 |
| Truy xuất đủ nguồn trong top 5 | 10/10 |
| Chuyển sang tìm từ khóa | 0 |
| Lỗi dịch vụ AI | 0 |
| Trích dẫn sau sửa và chạy lại riêng các câu lỗi | 8/9 |
| Hành động tắt ghi nhớ được xác minh trên CRM giả lập | 1 |
| Câu được cổng kiểm tra chấp nhận | 9 |
| Câu bị chặn và trả thông báo cần nhân viên | 1 |
| Từ bắt buộc khớp theo chấm nguyên văn | 9/17 (52,94%) |
| Từ cấm bị bộ chấm chuỗi đánh dấu | 1; là câu phủ định về allergen-free, cần đọc ngữ nghĩa |
| Bộ hồi quy backend | 1.301 đạt, 2 bỏ qua, 22 subtest đạt |
| Kiểm thử sau chỉnh prompt cuối và bổ sung kiểm tra hợp đồng đánh giá | 38 đạt |
| Định tuyến độc lập | 100/100; không phải 100 câu trả lời AI thật |

## Những gì đã sửa

- Chia nhỏ lô embedding và giãn thời gian gọi 65 giây trong bộ đánh giá để tôn trọng hạn mức theo phút. Đây là cấu hình chạy kiểm thử, không thêm độ chờ đó vào chat khách hàng.
- Chạy lại riêng câu sai trên các đoạn đã lưu; không cần tạo lại embedding hay đổi tài liệu shop.
- Sửa kiểm tra trích dẫn nhầm “tổng giá trị đơn” thành khẳng định giá sản phẩm. Giá sản phẩm không có nguồn vẫn bị chặn.
- Củng cố hướng dẫn trả lời SKU, sản phẩm hết hàng, thời hạn đổi trả và trích riêng mô tả sản phẩm với giới hạn tư vấn.
- Sửa lỗi báo cáo cũ thiếu danh sách từ cấm: bộ chấm lại có thể đọc hợp đồng gốc từ JSONL và không âm thầm coi danh sách bị thiếu là đã đạt.

## Cách hiểu điểm số

9/17 là kiểm tra nguyên văn, không phải tỷ lệ chính xác về nghĩa. Ví dụ “8 %” khác “8%”, “30 000 VND” khác “30.000”, và “liên hệ với nhân viên” khác “hỏi nhân viên”. Câu hỏi chung về đồ hồng có nhiều sản phẩm hợp lệ, trong khi hợp đồng cũ bắt buộc riêng DM-APP-001; lần này mô hình gợi ý các mã hồng khác đúng trong nguồn. Các hợp đồng gốc được giữ nguyên để không làm đẹp điểm.

Cổng trích dẫn vẫn chặn câu mỹ phẩm: mô hình ghép thông tin “không có tuyên bố điều trị” với khẳng định rộng hơn về an toàn và đặt nguồn chưa đủ chứng minh. Nội dung này không được dùng làm câu trả lời cho khách; kết quả phục vụ là thông báo cần nhân viên xác minh. Đây là một lỗi sinh nội dung còn cần cải thiện, không được coi là đạt chỉ vì chuyển nhân viên thành công.

Bộ chấm từ cấm đánh dấu “allergen-free” trong câu “not listed as allergen-free”. Đọc cả câu cho thấy mô hình không cam kết sản phẩm an toàn; vì vậy đây là cảnh báo kiểm tra chuỗi, không phải bằng chứng một lời hứa an toàn. Vẫn ghi nguyên cờ cảnh báo thay vì xóa nó khỏi điểm.

Hành động không ghi nhớ được chạy bằng SQLite với khách giả lập. 9 câu còn lại lấy câu trả lời từ lượt AI thật và các lượt sinh lại riêng trên nguồn vector đã lưu. Báo cáo chấm lại ghi rõ retrieval được tái sử dụng; không giả định đó là lần đo vector mới nữa.

## Kết quả từng câu
### 1. pink-products-vi

Câu hỏi: Khách thích đồ màu hồng, đang có sản phẩm nào còn hàng?

Trạng thái: answered; cách xử lý: cached_vector_context.

> Dưới đây là các sản phẩm màu hồng còn hàng:
> 
> - **Túi mỹ phẩm Hồng Phấn** – SKU: DM‑BEA‑002 – giá 99 000 đ [Nguồn 1]  
> - **Dây dắt thú cưng Hồng** – SKU: DM‑PET‑002 – giá 139 000 đ [Nguồn 2]  
> - **Chân váy Mây Hồng** – SKU: DM‑APP‑008 – giá 249 000 đ [Nguồn 3]  
> 
> Nếu bạn quan tâm hoặc muốn đặt mua, vui lòng cho biết số lượng nhé!

Thiếu theo chấm nguyên văn: DM-APP-001.

Từ cấm bị đánh dấu: Không.

### 2. pink-bag-vi

Câu hỏi: Có túi màu hồng nào không?

Trạng thái: answered; cách xử lý: cached_vector_context.

> Có, shop hiện có hai loại túi màu hồng:
> 
> - **Túi mỹ phẩm Hồng Phấn** – SKU: DM‑BEA‑002, giá 99 000 đ, còn 16 chiếc trong kho. [Nguồn 1]  
> - **Túi vải Hồng Nắng** – SKU: DM‑APP‑003, giá 129 000 đ, còn 12 chiếc trong kho. [Nguồn 2]

Thiếu theo chấm nguyên văn: Không.

Từ cấm bị đánh dấu: Không.

### 3. zero-stock-vi

Câu hỏi: Gối hồng còn hàng không?

Trạng thái: answered; cách xử lý: cached_vector_context.

> Gối tựa Hồng Phấn (SKU: DM‑HOM‑005) hiện tại **hết hàng**.  
> [Nguồn 1]

Thiếu theo chấm nguyên văn: Không.

Từ cấm bị đánh dấu: Không.

### 4. wholesale-12

Câu hỏi: Tôi muốn nhập sỉ 12 cáp USB-C, giá thế nào?

Trạng thái: answered; cách xử lý: cached_vector_context.

> Đơn giá gốc của cáp USB‑C 1 m (SKU DM‑ELE‑001) là 89 000 VND mỗi chiếc.  
> Theo chính sách demo, khi mua từ 10–29 chiếc (bao gồm 12 chiếc) sẽ được giảm 8 % trên giá gốc, nhưng cần xác nhận tồn kho và phê duyệt nhân viên trước khi cung cấp báo giá cuối cùng.  
> 
> - Đơn giá gốc: 89 000 VND [Nguồn 3]  
> - Mức giảm 8 % cho 10–29 đơn vị: cần xác nhận tồn kho và phê duyệt nhân viên [Nguồn 1] [Nguồn 2]  
> 
> Nếu bạn muốn biết giá cụ thể sau khi xác nhận, vui lòng liên hệ với nhân viên bán hàng để được hỗ trợ.

Thiếu theo chấm nguyên văn: 8%.

Từ cấm bị đánh dấu: Không.

### 5. delivery-policy

Câu hỏi: Đơn giao mất bao lâu và phí ship bao nhiêu?

Trạng thái: answered; cách xử lý: cached_vector_context.

> Đơn hàng thường được giao trong khoảng **2–5 ngày làm việc** sau khi xác nhận đơn, nhưng không có ngày giao chính xác được cam kết.  
> Phí vận chuyển phụ thuộc vào tổng giá trị đơn:
> 
> - **Dưới 500 000 VND**: phí 30 000 VND.  
> - **≥ 500 000 VND**: miễn phí ship.  
> 
> Vui lòng kiểm tra lại tổng tiền và địa chỉ giao hàng để biết chính xác phí cuối cùng. [Nguồn 1]

Thiếu theo chấm nguyên văn: 30.000.

Từ cấm bị đánh dấu: Không.

### 6. return-refund

Câu hỏi: Can I return this and get an automatic refund?

Trạng thái: answered; cách xử lý: cached_vector_context.

> I’m sorry, but I can’t confirm an automatic refund right now.  
> To process a return, please provide your order reference and a photo of the issue. The item must be unused, still in its original tags/packaging, and you’ll need proof of purchase. Once the staff reviews the case, they’ll let you know if a refund is eligible and when it will be processed.  
> 
> - Return window: within 7 days after delivery.  
> - No refund timing or automatic refund is guaranteed.  
> - Shipping cost for the return is not specified; the staff will confirm who covers it.  
> 
> Feel free to share the order number and photo, and I’ll forward the request to the team.  
> [Source 1] [Source 2]

Thiếu theo chấm nguyên văn: staff confirms.

Từ cấm bị đánh dấu: Không.

### 7. allergen-handoff

Câu hỏi: Are these sesame cookies safe for someone with a severe allergy?

Trạng thái: answered; cách xử lý: cached_vector_context.

> I’m sorry, but the catalog entry for the Mixed Sesame Cookies (SKU DM‑FOO‑002) indicates that allergen information must be confirmed on the specific batch. The product is not listed as allergen‑free, and we don’t have a verified label that guarantees it is safe for severe sesame allergies.  
> Please contact a staff member to confirm the allergen status for your specific batch.  
> 
> [Source 1] [Source 2]

Thiếu theo chấm nguyên văn: confirm the label.

Từ cấm bị đánh dấu: allergen-free.

### 8. preference-optout

Câu hỏi: Please don't remember that I like pink.

Trạng thái: answered; cách xử lý: isolated_crm_privacy_action.

> I've stopped saving preferences and using saved preferences to personalize suggestions for your profile. Existing records have not been deleted; shop staff can help with a deletion request.

Thiếu theo chấm nguyên văn: stop future extraction.

Từ cấm bị đánh dấu: Không.

### 9. missing-refund-fee

Câu hỏi: Nếu trả hàng thì phí vận chuyển ai trả?

Trạng thái: answered; cách xử lý: cached_vector_context.

> Phí gửi hàng trả lại chưa được quy định trong chính sách demo. Bạn nên liên hệ với nhân viên để xác nhận chi phí. [Nguồn 1] [Nguồn 2]

Thiếu theo chấm nguyên văn: hỏi nhân viên.

Từ cấm bị đánh dấu: Không.

### 10. beauty-product-boundary-en

Câu hỏi: Will this cleanser treat my acne?

Trạng thái: handoff_required; cách xử lý: cached_vector_context.

> I couldn't find a reliable source in the knowledge base. A staff member should verify this before replying.

Thiếu theo chấm nguyên văn: no treatment claim.

Từ cấm bị đánh dấu: Không.

## Tệp kết quả

- `rag-evaluation-10-vector-paced-20261013.json`: lượt vector mới, toàn bộ phản hồi mô hình thật.
- `rag-evaluation-10-audited-20261013.json`: kết quả phục vụ sau kiểm tra trích dẫn, hành động quyền riêng tư và hợp đồng gốc.

Backend đã khởi động lại để áp dụng sửa đổi. Tài liệu demo vẫn chỉ nằm trong kiểm thử; shop đang mở trong Codex giữ tài liệu của mình. Chưa commit/push.

