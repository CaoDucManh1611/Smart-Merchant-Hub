# Huấn luyện reranker gợi ý từ hành vi thật

Luồng retrieval Hybrid/BM25/RRF/PPR là code dùng chung: request luôn chạy trong tenant schema của shop và PPR chỉ nhận product weights của khách trong shop đó khi có consent. Reranker gợi ý sản phẩm cũng dùng chung code phục vụ; artifact và log được lưu riêng trong từng tenant, không gộp dữ liệu giữa shop.

Mọi shop luôn có thứ hạng nền ngay cả khi chưa đủ log để train model. BM25 của RAG và xếp hạng catalog đều đọc thuộc tính sản phẩm có cấu trúc như danh mục, hãng, model, tương thích, màu, size, chất liệu, tags và thông số. Các trường này phải được đưa vào metadata của tài liệu/sản phẩm; chúng được so với câu hỏi trong từng tenant. Sản phẩm còn bị giới hạn theo catalog và tồn kho của shop hiện tại. Khi model học hành vi của shop đạt quality gate, nó tinh chỉnh thứ hạng nền; RFM/sở thích chỉ tham gia khi khách đã đồng ý cá nhân hóa.

## Log được dùng

- Chỉ tạo impression sau khi chatbot gửi thành công và lưu được tin nhắn; danh sách ghi nhận là các sản phẩm thực sự xuất hiện trong nội dung gửi.
- Click, thêm vào quote/giỏ, mua, bỏ qua và hoàn tiền được nối với request gợi ý theo tenant, sản phẩm và cuộc hội thoại. Quote chỉ được tính là cart khi khách đã yêu cầu mua; các quote hỏi giá không được ghi nhận.
- Propensity của epsilon-greedy ghi xác suất chọn chiến lược tại request và từng impression. Dữ liệu không lưu raw query vào artifact huấn luyện.
- Feature RFM và sở thích chỉ được dùng khi request có snapshot cá nhân hóa được phép; model suy luận cũng bỏ nhóm feature đó nếu khách hiện không cho phép cá nhân hóa. RFM được kết hợp với relevance/affinity theo từng sản phẩm để tín hiệu cấp khách hàng có thể thay đổi thứ hạng.

## Huấn luyện và đánh giá

Chạy từ thư mục `backend`, với `PLATFORM_DATABASE_URL` và `TENANT_DATABASE_URL` trỏ đúng PostgreSQL:

```powershell
python scripts/train_live_recommendation_reranker.py --all-shops
```

`--all-shops` xử lý lần lượt mọi tenant đang `active` và `feature_enabled`; mỗi shop được train, đánh giá và lưu model riêng, không trộn dữ liệu. Có thể giới hạn vào một shop đã provision xong bằng `--business-id 7` (thay `7` bằng ID shop cần chạy). `--algorithm live_feedback_pairwise_reranker_v1` là mặc định; LightFM là lựa chọn có cùng baseline và gate:

```powershell
python scripts/train_live_recommendation_reranker.py --all-shops --algorithm lightfm_warp_rfm_v2
```

LightFM chỉ cần trong môi trường huấn luyện offline: `pip install -r requirements-lightfm.txt`. Serving không import gói này; nó đọc factor artifact nén. LightFM dùng WARP implicit feedback, factors 32 chiều mặc định, tối đa một thread, HMAC pseudonym cho customer ID và chỉ tạo user score khi khách hiện còn consent cá nhân hóa. User features kết hợp identity theo khách với bucket R/F/M theo quintile; ngưỡng quintile được fit riêng từng shop trên phần train trước holdout. Nếu thiếu snapshot RFM hiện hành, khách mới hoặc sản phẩm chưa có factor, serving giữ thứ hạng baseline. Chỉ chấp nhận model khi ít nhất 80% người dùng có tương tác dương trong train có snapshot RFM đủ trường. Hiện LightFM chỉ phục vụ `product`; service/rental chưa có cùng luồng canonical recommendation và feedback.

Lệnh dùng mặc định 180 ngày log gần nhất, huấn luyện pairwise logistic reranker và giữ 20% request mới nhất làm holdout theo thời gian. Báo cáo so sánh Precision@3 và NDCG@3 có trọng số nghịch đảo propensity chiến lược (giới hạn 5), cùng tỷ lệ mua/từ chối quan sát được trên impression. Impression không có phản hồi được dùng làm negative yếu; skip/refund là negative rõ hơn.

Mặc định artifact chỉ được lưu ở trạng thái chưa bật. `--activate` chỉ bật phục vụ nếu quality gate theo thời gian của shop đạt: NDCG@3 không giảm so với baseline, đủ consented customer/holdout, đủ độ phủ score, có validation cho toàn bộ top 3 và tỷ lệ vi phạm shop/status/tồn kho/thuộc tính bắt buộc không tăng. Pairwise còn yêu cầu 30 positive product events, 50 cặp train, 20 request train và 5 request holdout; LightFM dùng ngưỡng positive events/requests và yêu cầu ít nhất 80% request holdout tích cực được model chấm điểm:

```powershell
python scripts/train_live_recommendation_reranker.py --all-shops --activate
```

Để bật LightFM sau khi cài optional dependency:

```powershell
python scripts/train_live_recommendation_reranker.py --all-shops --algorithm lightfm_warp_rfm_v2 --activate
```

Khi mẫu chưa đủ, attempt được lưu theo shop và model đang active được giữ nguyên. Khi một candidate có đủ mẫu nhưng trượt quality gate, shop tự quay về baseline. Đây là đánh giá offline trên các sản phẩm đã hiển thị; NDCG/Precision từ log quan sát chưa thay thế A/B test, và chưa phải LinUCB theo từng sản phẩm. Bandit hiện chọn chiến lược ở mức request, warmup 50 kết quả cuối, epsilon mặc định 0.02 (giới hạn tối đa 0.05) và ghi propensity để hỗ trợ đánh giá có điều chỉnh thiên lệch. Rút consent xóa artifact reranker của shop và yêu cầu train lại từ dữ liệu còn consent.
