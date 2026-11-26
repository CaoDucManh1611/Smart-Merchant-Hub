# Ngrok migration — 25/11/2026

Trạng thái: PARTIAL / còn BLOCKED, không nghiệm thu toàn bộ.
Domain: vocalist-dreamy-corned.ngrok-free.dev → glitzy-confusion-casualty.ngrok-free.dev.

## File thay đổi
- .env: PUBLIC_BASE_URL, DOCKER_ALLOWED_HOSTS.
- backend/.env: PUBLIC_BASE_URL, CORS_ORIGINS, ALLOWED_HOSTS.
- frontend/vite.config.js: allowlist domain mới, bỏ các tunnel cũ.
- KHOI_DONG_SMH.bat: hướng dẫn lệnh tunnel đúng domain.
- KHOI_DONG_NGROK.ps1: lệnh mở đúng tunnel, kiểm tra tunnel đang chạy để tránh mở trùng.
- reports/ngrok-domain-scan-20261125.json: kết quả rà file cấu hình/source, gồm file ẩn/không được Git theo dõi, bỏ lịch sử Git/binary/cache/backup.
Bản sao cấu hình trước sửa: backups/ngrok-migration-20261125-130622. Có chứa cấu hình bí mật, chỉ lưu local, không chia sẻ.

## Dữ liệu/cấu hình bên ngoài
Chỉ sửa trường config.webhook_url của channels; không sửa tài khoản, đơn, tin nhắn, mật khẩu, token hoặc secret. 5 kênh disconnected được cập nhật URL lưu mà không kích hoạt lại. Zalo shop_3 channel10 cập nhật URL lưu nhưng nhà cung cấp BLOCKED InvalidToken. Zalo shop_7 channel8 và Telegram shop_7 channel10: setWebhook và getWebhookInfo xác nhận domain mới. Token/secret cũ được giữ nguyên.
Không restore/xóa volume/database. Không pull/reset Git. Các thay đổi trước đó được giữ.

## Bằng chứng kiểm thử
| Mục | Kết quả | Bằng chứng/giới hạn |
|---|---|---|
| Tunnel | PASS | Local API 4040 báo HTTPS domain mới → http://localhost:5173 |
| Public frontend | PASS | HTTP 200; trình duyệt mở landing page và màn hình đăng nhập SMH |
| Ngrok offline error | PASS tại thời điểm kiểm tra | Không thấy ERR_NGROK_320 khi mở domain mới; ngrok free có trang thông báo 6024 lần đầu |
| API reverse proxy | PASS | GET public /api/conversations → 403 Tenant context is required, tới đúng backend |
| CORS allowlist | PASS | Origin domain mới preflight 200, ACAO đúng domain; untrusted.example bị 400, không ACAO |
| Allowed Hosts | PASS | Host mới /health 200; host cũ và untrusted.example 400 |
| Backend, worker, frontend | PASS | Restart/recreate đúng runtime hiện tại, health kiểm tra sau khởi động |
| Zalo/Telegram shop7 | PASS cấu hình | Nhà cung cấp xác nhận webhook mới; chưa gửi tin hai chiều |
| Zalo shop3 | BLOCKED | Token lưu không giải mã được (InvalidToken); cần kết nối lại bằng tài khoản hợp lệ |
| Facebook local | PASS trạng thái startup | Connector đang chạy và được script xác minh; chưa thử gửi nhận |
| Instagram/Shopee | BLOCKED end-to-end | Startup xác định không kết nối hợp lệ hoặc không local; không tự kích hoạt |
| TikTok | BLOCKED | Credential không giải mã được; cần ghép nối lại |
| Login/logout/session refresh | BLOCKED kiểm thử tài khoản | Màn hình đăng nhập hiển thị; chưa có tài khoản kiểm thử được chỉ định. Session browser của localhost không tự chuyển sang origin mới |
| Realtime có xác thực | BLOCKED | Chưa có phiên kiểm thử; không thể kết luận chỉ từ proxy /ws |
| Pairing/download/EXE/WebView | BLOCKED end-to-end | Source/default build dùng localhost, không thấy hardcode domain cũ; chưa ghép nối mới hoặc chứng minh binary đã đóng gói |
| Dữ liệu người dùng | Không có thao tác xóa/khôi phục | Chỉ cập nhật config kênh; chưa có snapshot đếm trước migration nên không tuyên bố so sánh toàn bộ dữ liệu |

## Quét tham chiếu
Source/config runtime trên đĩa không còn domain cũ. test_media_upload_api.py giữ domain cũ làm fixture kiểm thử, không phải URL runtime. Backup và lịch sử Git giữ nguyên theo yêu cầu. Các log/cached history không bị sửa. Cấu hình connector trong AppData dùng backend http://127.0.0.1:8000, không cần chuyển sang tunnel. Không thấy source/build script hardcode domain cũ nên chưa rebuild EXE; binary end-to-end vẫn BLOCKED.

## Việc còn cần cập nhật/kiểm tra thủ công
- Meta Developer Dashboard nếu dùng OAuth: Valid OAuth Redirect URI = https://glitzy-confusion-casualty.ngrok-free.dev/api/oauth/meta/callback; App Domain = glitzy-confusion-casualty.ngrok-free.dev. Chưa có quyền dashboard để xác nhận.
- Meta Webhooks nếu dùng API thay local connector: cập nhật callback tương ứng đường dẫn đang đăng ký; cần đọc dashboard để biết đường dẫn chính xác, không đoán verify token.
- TikTok/Shopee OAuth/partner dashboard nếu đang dùng API: đổi origin của callback giữ nguyên path đã đăng ký; chưa xác định được cấu hình dashboard thực tế.
- Kết nối lại Zalo shop3 và TikTok có credential InvalidToken, không thay khóa mã hóa để chữa tạm.
- Đăng nhập trên domain mới và kiểm tra logout/refresh/session, ghép nối trên tài khoản thử; không gửi khách thật.
- Giữ cửa sổ ngrok đang chạy. Lần sau có thể chạy KHOI_DONG_NGROK.ps1. Script bat chính chỉ hiển thị lệnh ngrok, không tự mở tunnel.

## Khôi phục nếu cần
Phục hồi từng file từ backup nêu trên rồi recreate backend/worker và restart frontend bằng cùng project/compose. Với webhook provider cần đăng ký lại URL tunnel thực sự online; không chỉ phục hồi DB. Không thực hiện rollback tự động vì tunnel cũ có thể không còn hợp lệ.
