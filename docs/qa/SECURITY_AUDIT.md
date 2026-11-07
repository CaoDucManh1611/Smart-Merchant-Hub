# Security audit có kiểm soát

Nguồn checklist là [OWASP WSTG](https://owasp.org/projects/web-security-testing-guide). Lượt này chỉ áp dụng phạm vi kiểm tra an toàn có thể chạy, chưa phải chứng nhận đầy đủ WSTG.

|Hạng mục|Bằng chứng thực thi|Kết luận phạm vi|
|---|---|---|
|Missing/invalid token|5 đường API x 2 request; 401/403|PASSED cho 10 request này|
|Headers|nosniff và X-Frame-Options DENY trên response backend|PASSED cho response đã đọc|
|CORS origin lạ|Health không trả allow-origin cho qa-untrusted.invalid|PASSED cho origin được thử; credentials header có nhưng thiếu allow-origin|
|RBAC, IDOR, tenant, capability|Xem test IDs trong backend.xml|Theo kết quả từng ca fixture, chưa chứng minh mọi endpoint|
|Webhook signature, payment duplicate|Suite tests hiện có|Provider mock; real provider NOT RUN|
|Consent, memory, Graph tool quyền|Suite tests hiện có|Offline; race hai session cần test PG chuyên biệt|
|SQLi/XSS/SSRF/upload|Có test security hiện có, xem JUnit|Không suy rộng thành không có lỗ hổng; authenticated runtime scan NOT RUN|
|Production TLS/CSP/role ACL|Không có staging và role app được xác nhận|NOT VERIFIED|
|Secrets/PII trong log|Lượt probe không lưu body khách; không xuất .env|Chưa chạy secret scanner đầy đủ, NOT VERIFIED toàn repo|

Static review xác nhận main.py có CORS theo allowlist, credential flag theo cấu hình, TrustedHost/HTTPS middleware theo setting. SecurityHeadersMiddleware có nosniff/DENY và HSTS khi bật. Đây là sự tồn tại trong source, runtime production chưa được kiểm.

Consent race lịch sử còn OPEN theo báo cáo bàn giao. Test đọc/ghi sau revoke không tự chứng minh tính đúng đắn khi revoke và read chạy đồng thời. Không tự đóng finding này.
