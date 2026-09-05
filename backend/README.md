# Backend runbook

## Omnichannel media

Mọi media inbound được chuẩn hóa thành `NormalizedAttachment` và lưu ở bảng
`message_attachments`. Mỗi dòng gắn với `business_id`, `channel_id` và
`message_id`; token nhà cung cấp không trả về frontend.

Sau khi cập nhật code, chạy migration bằng Python trong container:

```powershell
docker compose exec backend python -m alembic upgrade head
```

Kiểm tra head:

```powershell
docker compose exec backend python -m alembic current
```

Frontend đọc `attachments[].media_url` dưới dạng URL proxy nội bộ đã ký, có
thời hạn ngắn. Cách này cần thiết vì thẻ ảnh/âm thanh/video của trình duyệt
không thể tự gửi header `X-Business-Id`. API thông thường vẫn có thể gọi
`GET /api/media/{attachment_id}` với header đó. Attachment khác tenant trả về
`404`; URL đã hết hạn hoặc media từ nhà cung cấp không còn khả dụng trả về
`401`, `502` hoặc `404`.

Gửi media từ inbox dùng:

```http
POST /api/conversations/{conversation_id}/send-media
X-Business-Id: 1
Content-Type: application/json

{"media_type":"audio","media_url":"https://public.example/audio.mp3","caption":"Nghe thử"}
```

Giao diện có thể upload trực tiếp file local bằng multipart:

```http
POST /api/conversations/{conversation_id}/media/upload-generic
X-Business-Id: 1
Content-Type: multipart/form-data

file=<binary>&media_type=audio&caption=Nghe thử
```

Endpoint này giữ nguyên bytes của audio/video/sticker/file và tạo URL HTTPS
ngắn hạn dưới `PUBLIC_BASE_URL` để provider tải file.

Telegram hỗ trợ image, audio, sticker, video và file qua các method Bot API
tương ứng. Zalo Bot Creator hỗ trợ image/audio/sticker; Facebook Messenger và
Instagram dùng attachment URL cho image/audio/video/file. Tổ hợp provider
không hỗ trợ trả về `422` trước khi ghi message thành công.

URL media phải truy cập được từ provider. Với file local, cần publish backend
qua HTTPS (ví dụ ngrok) và cấu hình `PUBLIC_BASE_URL` đúng domain đó.

## Kiểm thử

```powershell
cd backend
$env:PYTHONPATH = "$PWD\.migrationdeps;$PWD"
& 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_message_attachments.py tests/test_media_persistence.py tests/test_media_proxy.py tests/test_media_end_to_end.py -q
```

## CRM operations

The current schema is migrated with Alembic (head `20260905_0023`). The CRM
now includes tenant-scoped Customer 360 tags/segments, merge history and a
unified timeline; sales and purchase orders with guarded lifecycle transitions;
owner/admin/agent/viewer sessions; append-only audit logs; filtered reports;
workflow run history/retries and persisted notifications; document embedding
state with lexical fallback and explicit reindex; and measurement primitives
for rule suggestions, feature snapshots, experiments and contextual bandits.

For a fresh deployment, create the first real owner account from the backend
container. The password is prompted privately:

```powershell
docker compose exec backend python scripts/create_admin.py --business-id 1 --email owner@example.com --name "Shop Owner"
```

Then sign in under **Cài đặt**. Existing development installations can still
use the `X-Business-Id` header until an owner session is created; once a bearer
session is present, its tenant and role take precedence.

For production, set `ENVIRONMENT=production`, `AUTH_SECRET` and
`CHANNEL_ENCRYPTION_KEY` to long random values. In that mode all write
endpoints require a bearer session; the development header fallback is off.
Also set explicit `CORS_ORIGINS`, `ALLOWED_HOSTS`, HTTPS public/frontend URLs,
`FORCE_HTTPS=true`, `HSTS_ENABLED=true` and `RATE_LIMIT_ENABLED=true`. See
[`docs/production-security-runbook.md`](../docs/production-security-runbook.md)
for secret rotation, legacy credential retirement, Git history audit and
PostgreSQL backup/restore.
