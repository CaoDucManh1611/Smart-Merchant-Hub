# Owly CRM bổ sung cho `crm-completion` (không lấy WhatsApp)

## Kết luận nhanh

Không merge nguyên repo Owly. Owly là ứng dụng single-tenant: `Settings` và `BusinessHours` là singleton, các model không có `business_id`/`tenant_id`, và dùng Prisma riêng. Chỉ port các ý tưởng, adapter và UI cần thiết sang FastAPI/SQLAlchemy/PostgreSQL hiện có của `crm-completion`.

CRM Completion đã có các phần tương đương hoặc mạnh hơn: RAG/AI tools, Customer 360, đơn hàng/sản phẩm/tồn kho, ticket/workflow/worker, follow-up, CSAT, canned responses, Telegram/Zalo/Facebook/Instagram/Shopee/TikTok, tenant isolation, quota, MFA, audit, privacy, backup/restore và provider retry/circuit breaker.

## Phạm vi lấy từ Owly

### P0 — Nên port trước

#### 1. Email inbox hai chiều (IMAP + SMTP)

Owly có nhận email qua IMAP, trả lời qua SMTP và nối thread bằng `In-Reply-To`/`References`. CRM Completion hiện chỉ dùng SMTP cho OTP, chưa có email như một kênh hội thoại.

Phạm vi:

- Thêm cấu hình IMAP/SMTP theo từng shop; secret phải mã hóa, không lưu plaintext.
- Tạo inbound email adapter về contract `Conversation`/`Message` hiện có.
- Nhận diện customer theo email, hợp nhất lịch sử vào Customer 360.
- Giữ header thread và chống xử lý trùng message.
- Worker IMAP reconnect/backoff, dead-letter và health status.
- UI kết nối email, test connection, trạng thái listener và lỗi gần nhất.

Điều kiện hoàn tất: email đến tạo đúng hội thoại của shop, email trả lời nằm cùng thread, retry không tạo message trùng và shop A không đọc được email của shop B.

#### 2. Tác vụ xử lý hội thoại cho nhân viên

Owly có snooze, transfer, merge và macro. CRM Completion hiện có assignment, pause/resume bot và merge customer, nhưng chưa có đầy đủ thao tác ở cấp hội thoại.

Phạm vi:

- `snooze_until` và lịch tự mở lại hội thoại.
- Chuyển hội thoại giữa nhân viên/phòng ban, lưu lịch sử assignment.
- Merge hai hội thoại cùng customer với preview, kiểm tra tenant và undo.
- Macro nhiều hành động: đổi trạng thái, gán người, gắn tag, thêm note, gửi canned response.
- Audit cho từng hành động và idempotency key cho thao tác lặp.

Điều kiện hoàn tất: mọi thao tác chỉ tác động trong `business_id`, có audit, không làm mất message và có thể khôi phục merge.

### P1 — Bổ sung để CRM vận hành như trung tâm CSKH

#### 3. Department, expertise và availability routing

Owly phân tuyến theo phòng ban, chuyên môn và trạng thái sẵn sàng. CRM Completion mới có user/role/permission và assignment, chưa có mô hình chuyên môn.

Phạm vi:

- Department theo shop.
- Expertise/tag chuyên môn của từng user.
- Availability hiện tại và lịch làm việc của nhân viên.
- Bộ định tuyến ưu tiên: chuyên môn khớp → cùng department → người đang rảnh → hàng đợi fallback.
- API/UI quản lý department, thành viên, chuyên môn và availability.

Điều kiện hoàn tất: ticket/complaint mới được route ổn định, không gán sang user khác shop và có lý do route trong audit/timeline.

#### 4. Business hours và SLA có cấu hình

CRM Completion đã có business-hours JSON và SLA cố định theo priority. Owly có UI timezone/lịch tuần/offline message và SLA theo channel + priority.

Phạm vi:

- Chuẩn hóa business hours theo từng shop, timezone và ngày nghỉ.
- Offline message theo kênh, không chặn AI khi shop cho phép AI hoạt động 24/7.
- SLA rule theo channel/priority, first-response và resolution target.
- Tính SLA chỉ trong giờ làm, cảnh báo sắp quá hạn/quá hạn qua worker.
- Dashboard SLA compliance và lịch sử thay đổi cấu hình.

Điều kiện hoàn tất: cùng một ticket cho ra cùng deadline ở mọi worker, đổi timezone không làm sai deadline, và SLA không chạy chéo tenant.

#### 5. Outbound webhook management

Owly có màn tạo webhook, test payload, HMAC signature và delivery history. CRM Completion hiện chủ yếu xử lý inbound webhook của provider; chưa có catalog đích webhook cho shop.

Phạm vi:

- Webhook endpoint theo shop, event subscription, headers được mã hóa.
- Payload preview/test với request ID và HMAC signature.
- Bảng delivery: status, attempts, response code, last error, next retry.
- Retry phải chạy qua `crm_job_worker`/Redis durable, không dùng `setTimeout` trong request process.
- Rate limit, circuit breaker, disable sau nhiều lỗi và nút retry thủ công.

Điều kiện hoàn tất: delivery được truy vết end-to-end, retry qua restart worker vẫn tiếp tục, secret không xuất hiện trong log và không gửi event sang shop khác.

### P2 — Chỉ làm sau khi P0/P1 ổn định

#### 6. Campaign/segment/broadcast

Owly có Campaign theo channel, segment, lịch chạy và số lượng đã gửi. CRM Completion đã có saved customer segments và follow-up, nhưng chưa có campaign/broadcast thực sự.

Chỉ port khi có đủ:

- Campaign tenant-scoped và consent/opt-out.
- Preview số người nhận trước khi chạy.
- Schedule qua worker, rate limit theo provider và idempotency từng recipient.
- Theo dõi sent/delivered/failed/opt-out.

Không copy nguyên `execute campaign` của Owly: code hiện tại chủ yếu đếm target và tạo message trong DB, chưa bảo đảm gửi thật qua provider.

#### 7. Visual flow builder

Owly có node `message`, `question`, `condition`, `action`, `transfer`, `end` và validator unreachable node. CRM Completion đã có workflow JSON/action engine.

Chỉ lấy:

- Schema node/edge và validator của flow.
- UI kéo-thả nếu cần cho nhân viên không kỹ thuật.
- Biên dịch flow về workflow engine hiện có.

Không tạo runtime thứ hai; mọi execution vẫn phải đi qua worker, permission, quota và audit của CRM Completion.

#### 8. SMS customer channel và Phone/Voice

Owly có Twilio SMS và Twilio Voice + call log/STT/TTS. Đây là kênh tùy chọn, không liên quan OTP email hiện tại.

- SMS: chỉ làm nếu sản phẩm cần CSKH qua SMS; phải có opt-in, chống spam và delivery status.
- Phone/Voice: tách thành dự án riêng vì cần Twilio production, ghi âm, lưu trữ, chi phí STT/TTS và chính sách đồng ý ghi âm.

## Những phần không port

- WhatsApp QR/Business API — loại khỏi phạm vi theo yêu cầu.
- Owly Prisma schema, singleton settings, auth/session và UI nguyên khối.
- Knowledge base/RAG, Customer CRM cơ bản, ticket, canned response, analytics và webhook retry dạng cũ vì CRM Completion đã có hoặc có kiến trúc tenant an toàn hơn.
- Campaign/flow runtime của Owly nếu chưa bọc tenant, consent, idempotency và worker bền vững.

## Thứ tự triển khai đề xuất

1. Email IMAP/SMTP + inbound email adapter.
2. Snooze/transfer/merge conversation + macro.
3. Department/expertise/availability routing.
4. Business hours và SLA rule configurable.
5. Outbound webhook console và delivery worker.
6. Campaign/segment/broadcast.
7. Visual flow builder.
8. SMS hoặc Phone/Voice nếu có nhu cầu thương mại rõ ràng.

## Tiêu chuẩn bắt buộc khi port

- Mọi model/API/query đều có `business_id` và tenant DB đúng ngữ cảnh.
- Token/password/IMAP/SMTP/API key được mã hóa; log chỉ chứa dữ liệu đã redacted.
- Có permission, quota, audit, idempotency và retry cho mọi side effect.
- Có migration Alembic, backend test, frontend contract test và release smoke test.
- Không merge code Owly trực tiếp vào `crm-completion`; chỉ chuyển logic sau khi viết lại theo contract hiện tại.

## Nguồn đối chiếu Owly

- `work/owly/README.md`
- `work/owly/docs/wiki/Architecture.md`
- `work/owly/docs/wiki/Email-Channel.md`
- `work/owly/docs/wiki/Team-and-Departments.md`
- `work/owly/docs/wiki/Business-Hours-and-SLA.md`
- `work/owly/docs/wiki/Webhooks.md`
- `work/owly/src/lib/campaigns.ts`
- `work/owly/src/lib/flow-builder.ts`
