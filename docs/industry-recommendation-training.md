# Huấn luyện gợi ý từ bộ dữ liệu ngành

Chạy lệnh từ thư mục gốc repository. Dữ liệu nguồn nằm ngoài Git ở `D:\CRM_Industry_Datasets`.

```powershell
python scripts\train_industry_recommender.py --source dunnhumby --max-events 0
python scripts\train_industry_recommender.py --source hm --max-events 500000
python scripts\train_industry_recommender.py --source olist --max-events 0
python scripts\train_industry_recommender.py --source retailrocket --max-events 0
```

Mỗi lượt tạo thư mục riêng dưới `D:\CRM_Industry_Datasets\trained_models\<source>\run_*` gồm:

- `rfm_profiles.csv`: Recency, Frequency, Monetary và mã cụm phân tích.
- `rfm_segmenter.joblib`: `StandardScaler + MiniBatchKMeans`.
- `next_basket_ranker.joblib`: `StandardScaler + LogisticRegression` để xếp hạng giỏ mua tiếp theo so với sản phẩm âm được lấy mẫu.
- `training_report.json`: số dòng đọc, giới hạn lấy mẫu, Precision@5, Recall@5, NDCG@5 và giới hạn của lượt train.

Mặc định đọc tối đa 500.000 dòng mua để tránh dùng quá nhiều RAM; `--max-events 0` đọc toàn bộ. Nên chạy Dunnhumby và Olist đầy đủ trước; H&M có thể chạy tăng dần bằng cách tăng giới hạn.

## Giới hạn và cách dùng

- Giữ mỗi ngành và bộ nguồn riêng: ID khách, ID sản phẩm, tiền tệ và cách ghi nhận giao dịch không dùng chung được.
- Ranker dùng nhãn proxy “nằm trong giỏ kế tiếp” với negative sampling và chia dữ liệu theo thời gian. Các metric là benchmark next-basket, không phải conversion uplift hay chất lượng câu trả lời RAG.
- Retailrocket không có doanh thu nên Monetary không khả dụng; báo cáo đánh dấu điều này.
- Các bộ công khai không chứa truy vấn khách và danh sách sản phẩm đã được RAG hiển thị. Vì vậy không thể học trọng số Gemini/BM25/RRF/PPR hoặc huấn luyện LinUCB đúng nghĩa từ chúng.
- Artifact tạo ra là benchmark offline, có ID cục bộ của bộ dữ liệu và không được nạp vào tenant thật. CRM hiện vẫn tính hồ sơ RFM theo dữ liệu đơn của từng shop và nhận ứng viên từ RAG.
- Muốn huấn luyện reranker RAG có giám sát, cần log cho từng lần hiển thị: query, RFM snapshot, candidate product IDs, điểm BM25/vector/RRF/PPR, vị trí hiển thị và phản hồi click/cart/purchase/skip.
- Chỉ huấn luyện LinUCB sau khi có các lượt hiển thị, hành động được chọn, xác suất chọn và kết quả thật. Không xem đơn hàng tĩnh là log khám phá của bandit.
