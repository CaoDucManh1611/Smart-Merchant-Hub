# CRM completion checklist

Mục tiêu: kiểm thử và hoàn thiện toàn bộ luồng từ nhận tin nhắn đến chăm sóc
khách hàng, tạo đơn, vận hành và bảo mật tenant.

## Phân chia workstream

### `feat/crm-ai-commerce`

- Transactional intent router cho tra cứu đơn/đơn nháp/hủy đơn.
- RAG nhận diện sản phẩm, combo, số lượng, giá và tồn kho.
- Customer collection: tên, số điện thoại, email, địa chỉ.
- Validation dữ liệu ngay khi nhận.
- Tạo draft và xác thực OTP sau draft, trước xác nhận.
- Idempotency inbound/outbound, chống bot trả lời trùng.
- State machine xác nhận, hủy đơn, handoff khi cần người thật.

### `feat/crm-customer-ops-ui`

- Customer 360 và Unified Timeline.
- Actor type rõ ràng: khách hàng, bot, nhân viên, hệ thống.
- Human takeover, phân công, tag, ghi chú, ticket, SLA, CSAT.
- Mask email/số điện thoại; tên vẫn hiển thị đầy đủ.
- UI inbox, bảng đơn, timeline và Customer 360 ở desktop/tablet/mobile.
- Loading, empty, error, retry, keyboard focus và accessibility.

### `feat/crm-platform-quality`

- Tenant isolation, quota, role/permission, session và audit.
- Mã hóa token kênh, rate limit, MFA-ready, export/xóa/ẩn danh dữ liệu.
- Webhook/provider reliability, retry, health check, backup/restore.
- Test đa kênh và release smoke test.
- Dashboard usage, lỗi provider, AI cost và SLA.

## P0 – smoke test bắt buộc

- [ ] Đăng nhập đúng/sai, hết session, logout tất cả thiết bị.
- [ ] Chọn một hội thoại trên inbox và mở được Customer 360 tương ứng.
- [ ] `alo`/`chào` nhận đúng lời chào mặc định.
- [ ] Hỏi sản phẩm trả đúng tên, giá và tồn kho.
- [ ] `20 cái bin` và `6 combo` được hiểu đúng số lượng.
- [ ] Tạo draft không tạo đơn trùng và không trừ tồn kho hai lần.
- [ ] Sai định dạng email/số điện thoại bị chặn ngay.
- [ ] OTP chỉ gửi sau khi draft được tạo.
- [ ] Chưa xác thực không thể chốt đơn chính thức.
- [ ] Cùng một webhook gửi lại chỉ tạo một tin bot và một timeline event.
- [ ] Nhân viên takeover thì bot dừng ngay.
- [ ] Tin nhắn được gắn đúng actor trong Unified Timeline.
- [ ] Số điện thoại/email được che; tên khách hiển thị đầy đủ.
- [ ] Một tenant không đọc được khách, đơn, tài liệu hoặc token của tenant khác.

## Ma trận nghiệp vụ cần kiểm thử

### Bán hàng

- [ ] Sản phẩm tồn kho đủ.
- [ ] Hết hàng.
- [ ] Số lượng vượt tồn kho.
- [ ] Khách đổi sản phẩm/số lượng.
- [ ] Khách gửi thiếu thông tin.
- [ ] Khách đổi ý trước xác nhận.
- [ ] Khách hủy draft.
- [ ] Hủy đơn `confirmed`, `packing`, `shipping`, `completed` theo đúng chính sách.
- [ ] Thanh toán chưa trả, trả một phần, trả đủ, hoàn tiền.
- [ ] Giá/stock thay đổi trong lúc draft vẫn không tạo dữ liệu sai.
- [ ] Đơn có logistics provider, tracking code và shipment status.

### Customer care

- [ ] Khiếu nại/đổi trả/hàng lỗi tự tạo ticket ưu tiên cao.
- [ ] Ticket được gán đúng nhân viên/nhóm.
- [ ] SLA quá hạn tạo cảnh báo.
- [ ] Follow-up đơn nháp/bỏ giỏ được tạo và hủy đúng điều kiện.
- [ ] CSAT gửi sau khi ticket resolved/closed.
- [ ] Ghi chú nội bộ không xuất hiện với khách.
- [ ] Merge identity nhiều kênh không gộp nhầm khách.

### Đa kênh

- [ ] Telegram, Zalo, Facebook, Instagram, TikTok nhận tin.
- [ ] Gửi text, ảnh, file, sticker/video theo giới hạn provider.
- [ ] Webhook đúng chữ ký được nhận.
- [ ] Webhook sai chữ ký bị từ chối.
- [ ] Provider timeout/retry không tạo outbound trùng.
- [ ] Channel bị tắt không làm hỏng inbox chung.

### RAG và AI

- [ ] Upload tài liệu, parse, chunk, embedding, reindex.
- [ ] Xóa tài liệu không còn được truy hồi.
- [ ] Hỏi chính sách dùng RAG.
- [ ] Hỏi trạng thái/giá/đơn dùng database/tool, không dùng RAG để bịa.
- [ ] Không tìm thấy context có fallback an toàn.
- [ ] LLM/embedding key lỗi thì xoay key và không log raw secret.
- [ ] Tool không được gọi ngoài allow-list hoặc ngoài tenant.

## Test kỹ thuật và release gate

### Backend

```powershell
cd backend
python -m pytest -q
```

Không dùng `-k not ...` trong release gate. Nếu môi trường chưa chạy được
Alembic hoặc security suite, phải ghi rõ blocker và sửa trước khi merge.

### Frontend

```powershell
cd frontend
npm test
npm run build
```

### Smoke và dữ liệu

- [ ] `alembic upgrade head` chạy trên database rỗng.
- [ ] Migration chạy được trên database có dữ liệu cũ.
- [ ] Backup tạo được và restore thử thành công.
- [ ] Health check báo đúng trạng thái database, queue và provider.
- [ ] Không có secret/OTP/token raw trong log, response hoặc bundle frontend.
- [ ] Không có lỗi console nghiêm trọng ở các màn hình chính.

## Cải tiến CRM sau khi qua P0

| ID | Cải tiến | Mục tiêu |
|---|---|---|
| IMP-001 | Conversation state machine | Bot biết đang chọn sản phẩm, lấy thông tin, chờ OTP, chờ xác nhận hay handoff. |
| IMP-002 | Inventory reservation | Giữ tồn kho tạm thời cho draft và tự trả kho khi draft hết hạn. |
| IMP-003 | AI evaluation dashboard | Theo dõi độ chính xác, handoff rate, tool error, duplicate reply và conversion. |
| IMP-004 | CRM operations dashboard | Theo dõi inbox chưa xử lý, ticket quá SLA, draft và lead nóng. |
| IMP-005 | Unified event/audit model | Truy vết một thao tác từ inbound → bot → tool → order → timeline. |
| IMP-006 | Saved views and bulk actions | Lọc/phân công/gắn tag nhiều hội thoại an toàn, có audit. |
| IMP-007 | Data lifecycle | Chính sách retention, export, xóa và ẩn danh theo tenant. |
| IMP-008 | Provider circuit breaker | Tự tạm dừng provider lỗi và hiển thị trạng thái cho nhân viên. |

## Quy tắc merge ba nhánh

1. Mỗi nhánh chỉ sửa phạm vi đã phân công; tránh cùng sửa một component lớn nếu
   không cần thiết.
2. Trước khi mở PR, cập nhật từ `crm-completion`, chạy test riêng của nhánh và
   ghi rõ migration/API/UI thay đổi.
3. Merge theo thứ tự: `crm-ai-commerce` → `crm-customer-ops-ui` →
   `crm-platform-quality`.
4. Sau mỗi lần merge chạy lại toàn bộ backend, frontend, migration và manual
   smoke matrix; không chỉ dựa vào test của từng nhánh.
5. Chỉ merge vào `crm-completion` khi toàn bộ P0 pass và không còn dữ liệu nhạy
   cảm trong UI/log.

## Definition of done

- [ ] Tất cả P0 pass trên staging với ít nhất hai kênh thật.
- [ ] P1 trong `docs/bug-backlog.md` đã có test hồi quy.
- [ ] Không có duplicate outbound, lộ PII hoặc cross-tenant access.
- [ ] Backend/frontend build xanh.
- [ ] Migration, backup/restore và rollback đã được thử.
- [ ] Release checklist và bug backlog được cập nhật kết quả thực tế.

