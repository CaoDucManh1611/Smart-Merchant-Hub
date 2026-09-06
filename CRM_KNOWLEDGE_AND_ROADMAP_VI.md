# Smart Merchant Hub CRM
## Toàn bộ nghiệp vụ đã xây dựng, kiến thức bàn giao và kế hoạch phát triển

Ngày cập nhật: 04/09/2026  
Nhánh tích hợp hiện tại: crm-completion  
Mốc code bàn giao: 91e0b18 — checkpoint CRM completion  
Schema database hiện tại: Alembic 20260904_0022 (head)

---

## 1. Mục tiêu sản phẩm

Smart Merchant Hub là CRM đa kênh cho shop. Hệ thống gom tương tác từ các kênh bán hàng về một nơi, liên kết tương tác với hồ sơ khách hàng, hỗ trợ nhân viên bán hàng và CSKH, quản lý đơn hàng, tự động hóa, báo cáo và trợ lý AI.

Hệ thống có hai loại nghiệp vụ đơn hàng cần phân biệt:

- Sales Order: đơn shop bán cho khách hàng cuối.
- Purchase Order: đơn shop nhập hàng hoặc mua dịch vụ từ nhà cung cấp. Nếu shop mua gói chatbot/dịch vụ từ Smart Merchant Hub thì đó cũng là một nghiệp vụ mua của shop, không phải đơn khách cuối.

Zalo cá nhân không được xem là một kênh tích hợp hợp lệ nếu không có API chính thức. Phần Zalo hiện dùng Zalo Bot Creator.

---

## 2. Kiến trúc CRM

- Frontend: Vue 3 + Vite.
- Backend: FastAPI + Uvicorn.
- Database: PostgreSQL + pgvector.
- Migration: Alembic.
- Chạy dịch vụ: Docker Compose gồm db, backend và frontend.
- Realtime: WebSocket tại /ws/conversations.
- Router API chính: backend/app/api/router.py.
- Màn hình CRM chính: frontend/src/App.vue.
- Các tiện ích frontend: channel-utils.js, customer-utils.js, media-utils.js, ticket-utils.js.

Các nhóm model chính:

- Customer, CustomerIdentity, CustomerFact, CustomerMerge, CustomerNote.
- Conversation, Message, MessageAttachment.
- Product, SalesOrder, PurchaseOrder.
- Lead, Ticket, TicketEvent.
- User, AuthSession, AuditLog.
- Workflow, WorkflowRun, Notification.
- Document, DocumentChunk và các bảng trạng thái embedding.
- Recommendation và experimentation measurement.

---

## 3. Customer 360

### Đã làm

- Hồ sơ customer theo business.
- Danh sách conversation thuộc customer.
- Một customer có nhiều identity theo kênh.
- Identity cho Facebook, Instagram, Telegram, Zalo và các kênh khác khi adapter cung cấp.
- Unified timeline của customer.
- Timeline có message, ticket, order và event nghiệp vụ đã lưu.
- Customer note.
- Customer facts:
  - fact_type.
  - fact_key.
  - fact_value.
  - confidence.
  - source_type.
  - source_message_id.
  - source_order_id.
  - is_verified.
  - thời điểm quan sát.
- API tạo, xem, sửa và xóa customer fact.
- API thêm và xóa tag ở customer.
- Danh mục tag.
- Workflow có thể tự thêm tag.
- Merge customer có preview, merge record và inactive source marker.
- Tenant isolation khi xem customer, identity, fact, tag và timeline.

API chính:

- GET /api/customers.
- GET /api/customers/{customer_id}.
- GET /api/customers/{customer_id}/identities.
- GET /api/customers/{customer_id}/timeline.
- GET/POST/PATCH/DELETE /api/customers/{customer_id}/facts.
- GET/POST/DELETE /api/customers/{customer_id}/tags.
- POST /api/customers/{customer_id}/merge-preview.
- POST /api/customers/{customer_id}/merge.

### Cách hiểu nghiệp vụ

Customer là hồ sơ hợp nhất của người mua hoặc người liên hệ. Conversation là một luồng trao đổi. Identity là định danh của cùng người đó trên từng channel. Không được dùng conversation làm customer và không được dùng tên mặc định của một kênh để ghi đè tên customer thật.

### Còn thiếu

- Gợi ý customer trùng dựa trên email, số điện thoại và identity tương đồng.
- Màn hình xác nhận merge rõ ràng hơn.
- Undo/split merge có kiểm soát.
- Segment lưu được và lọc theo nhiều tag.
- Lịch sử thay đổi hồ sơ và tag hiển thị đầy đủ trên timeline.
- Chuẩn hóa quy tắc ưu tiên tên, avatar và thông tin liên hệ.

---

## 4. Unified Inbox và đa kênh

### Đã làm

- Danh sách conversation.
- Xem message theo conversation.
- Lọc inbox theo Facebook, Instagram, Telegram và Zalo.
- WebSocket để cập nhật conversation mới.
- Inbound message từ Facebook Messenger.
- Inbound message từ Instagram Messaging.
- Inbound và outbound từ Telegram Bot.
- Inbound/outbound nền tảng cho Zalo Bot Creator.
- Khung adapter cho Shopee và TikTok.
- Chuẩn hóa payload channel về message nội bộ.
- Tìm channel theo channel_type và external_account_id.
- Tạo hoặc lấy customer/conversation khi webhook nhận tin.
- Chống lưu trùng bằng external message id ở adapter đã hỗ trợ.
- Gửi phản hồi text từ UI qua channel adapter.
- Ghi outbound message vào conversation để timeline không bị mất chiều trả lời.

Webhook route:

- /api/webhooks/facebook.
- /api/webhooks/instagram.
- /api/webhooks/telegram.
- /api/webhooks/zalo.
- /api/webhooks/shopee.
- /api/webhooks/tiktok.

### Giới hạn kênh

- Facebook và Instagram phụ thuộc Meta App, Page access token, quyền ứng dụng và scoped recipient ID.
- Account khách vãng lai có thể không gửi được nếu Meta App chưa Live hoặc chưa đủ quyền.
- Telegram phải dùng bot token đúng và webhook secret phải khớp.
- Zalo phải dùng Bot Creator token và secret đúng; Zalo cá nhân không nằm trong API này.
- Domain ngrok phải còn online. Nếu endpoint offline thì webhook provider không thể gửi sự kiện.
- Không đặt access token thật vào frontend, Git hoặc chat chia sẻ.

---

## 5. Media đa kênh

### Đã làm

- Contract chung cho ảnh, audio, sticker, video và file.
- Lưu message attachment theo tenant.
- Lưu media_type, media_url và metadata provider.
- Media proxy an toàn:
  GET /api/media/{attachment_id}.
- Gửi media:
  POST /api/conversations/{conversation_id}/send-media.
- Có xử lý media inbound và outbound ở các adapter có hỗ trợ.
- Frontend có renderer cho ảnh và audio controls.
- Có nhận diện sticker và audio dù provider có thể trả URL tạm thời.

### Vấn đề cần tiếp tục

- Provider URL hết hạn hoặc trả 403 phải có fallback rõ ràng.
- Kiểm tra ảnh/audio/sticker trên Chrome và Edge.
- Bổ sung trạng thái loading, retry và lỗi tải media.
- Kiểm tra format audio thực tế của từng provider.
- Không cố ép một provider gửi loại media mà API provider không hỗ trợ.

---

## 6. Product, Sales Order và Purchase Order

### Product

- API sản phẩm.
- SKU, tên, mô tả, giá, tồn kho và trạng thái.
- Màn hình sản phẩm cơ bản.
- Dữ liệu product thuộc business.

### Sales Order

Sales Order là đơn bán cho khách cuối.

- Tạo và xem sales order.
- Customer/conversation có thể liên kết với đơn.
- Vòng đời đơn và transition status.
- Kiểm tra quyền và tenant.
- Có dữ liệu để báo cáo doanh thu và conversion.

### Purchase Order

Purchase Order là đơn shop mua từ nhà cung cấp hoặc mua dịch vụ.

- Bảng purchase_orders đã có migration.
- API danh sách, tạo, xem chi tiết, cập nhật và transition.
- Trạng thái đơn được kiểm tra.
- Dữ liệu thuộc business.
- Phân biệt với sales order trong API và báo cáo.

API liên quan:

- backend/app/api/sales.py.
- backend/app/api/purchase_orders.py.

### Còn thiếu

- Supplier master data.
- Line item đầy đủ và snapshot giá.
- Nhận hàng một phần hoặc nhiều lần.
- Cập nhật tồn kho khi nhận hàng.
- Thanh toán, công nợ và chứng từ.
- Hủy đơn có lý do.
- Liên kết purchase order với dịch vụ/gói chatbot Smart Merchant Hub.
- Báo cáo chi phí nhập hàng và biên lợi nhuận.

---

## 7. Lead và Sales Pipeline

### Đã làm

- Lead thuộc business.
- Trạng thái pipeline.
- Tạo và cập nhật lead.
- Gắn lead với customer/conversation khi có dữ liệu.
- Đếm lead và trạng thái trong báo cáo.

### Còn thiếu

- Kanban pipeline đầy đủ.
- Lead scoring.
- Tự chuyển conversation thành lead.
- Gắn nguồn campaign/channel.
- Forecast doanh thu theo cơ hội.
- Quy tắc tự động chuyển stage.

---

## 8. CSKH, Ticket và SLA

### Đã làm

- Tạo ticket từ customer/conversation.
- Tiêu đề, mô tả, ưu tiên và trạng thái.
- Phân công nhân viên.
- SLA deadline.
- Đếm tổng ticket và ticket quá SLA.
- Ticket event lưu lịch sử xử lý.
- Kiểm tra conversation và customer phải cùng business.
- Quyền đọc/ghi ticket.

API chính:

- backend/app/api/tickets.py.

### Còn thiếu

- Comment ticket theo từng nhân viên.
- Lịch sử xử lý hiển thị dạng activity feed đẹp hơn.
- Gán lại conversation và ticket trong inbox.
- SLA notification theo thời gian còn lại.
- Escalation khi quá hạn.
- Template trả lời theo loại ticket.
- Liên kết ticket với sales order và sản phẩm lỗi.

---

## 9. Team, đăng nhập, phân quyền và audit

### Đã làm

- Login.
- GET /api/auth/me.
- Logout.
- Session lưu trong database.
- Owner, admin và member.
- Guard cho read, write và admin.
- CRUD thành viên team cơ bản.
- Audit log append-only.
- Script tạo owner tại backend/scripts/create_admin.py.
- Migration auth/audit tại 20260904_0019.

### Còn thiếu

- Mời thành viên qua email.
- Reset password và đổi password.
- Refresh token hoặc cơ chế session rotation.
- Khóa tài khoản, disable user và revoke toàn bộ session.
- UI ẩn/khóa hành động theo role.
- Permission theo module cụ thể.
- Audit đầy đủ cho credential, merge, order, export dữ liệu và thay đổi quyền.
- Cấu hình cookie/session an toàn khi triển khai production.

---

## 10. Workflow Automation

### Đã làm

- Workflow có trigger event, điều kiện và action.
- Event message.created.
- Điều kiện theo channel.
- Action thêm tag customer.
- Notification nghiệp vụ được persist.
- Workflow run và payload event được persist.
- Retry run.
- Endpoint dispatch workflow.
- Đã kiểm chứng workflow Telegram tự thêm tag khach moi và ga.

Các file chính:

- backend/app/api/workflows.py.
- backend/app/services/workflow_engine.py.
- backend/app/models/workflow.py.
- backend/app/models/notification.py.

### Còn thiếu

- Worker/queue thật thay cho dispatch thủ công.
- Scheduler cho delayed action.
- Retry backoff và dead-letter state.
- Idempotency key chống chạy lặp.
- Version workflow.
- Preview điều kiện trước khi bật.
- Lịch sử action chi tiết.
- SLA reminder tự động.
- Các trigger order.created, ticket.overdue, lead.stage_changed và payment.received.

---

## 11. Báo cáo CRM

### Đã làm

- CRM overview.
- CSV overview.
- Spend theo supplier.
- Hiệu suất agent.
- Số lượng customer, conversation, lead, ticket và order.
- Số ticket quá SLA.
- Bộ lọc tenant.

API chính:

- backend/app/api/reports.py.

### Còn thiếu

- Doanh thu theo Facebook, Instagram, Telegram, Zalo và campaign.
- Funnel conversation → lead → sales order → paid.
- Attribution theo first touch, last touch và assisted touch.
- Hiệu suất agent theo thời gian phản hồi, SLA và doanh thu.
- Biểu đồ theo ngày/tuần/tháng.
- Drill-down từ số liệu về conversation/order gốc.
- Export báo cáo theo bộ lọc.
- Kiểm tra timezone và tiền tệ.

---

## 12. Knowledge Base và RAG

### Đã làm

- Upload tài liệu theo business.
- Lưu document và document chunk.
- Trạng thái indexing.
- Reindex và xóa tài liệu.
- Retrieval theo tenant.
- Lexical/hybrid retrieval.
- Auto-reply có context từ tài liệu.
- Khi không có chunk liên quan thì bỏ qua auto-reply, tránh trả lời bịa.
- Lưu embedding state, retry metadata và source bytes để reindex.
- Đã kiểm tra tài liệu rag_test_lunari.txt ở trạng thái ready với 5 chunks.
- Có log các lần chạy RAG.

API:

- backend/app/api/documents.py.
- backend/app/api/chat.py.

### Các lỗi đã gặp và cách hiểu

- Gemini embedding hết quota làm indexing retry nhiều lần.
- Embedding dimension 3072 vượt giới hạn HNSW 2000 chiều nên HNSW bị bỏ qua.
- Package google.generativeai phát cảnh báo deprecated.
- Nếu tài liệu chưa có chunk ready thì chatbot không nên auto-reply.
- Lỗi JSON trong PowerShell thường do gửi object PowerShell thay vì chuỗi JSON hợp lệ.

### Còn thiếu

- Chuyển sang SDK Google được hỗ trợ.
- Worker reindex nền.
- Retry quota có lịch và giới hạn concurrency.
- Provider fallback khi Gemini hết quota.
- Màn hình tiến độ indexing, lỗi và nút retry.
- Bộ câu hỏi chuẩn để đánh giá retrieval.
- Citation/source trong câu trả lời.
- Chính sách xóa và lưu giữ source bytes.
- Cấu hình dimension nhất quán giữa env, schema và model embedding.

---

## 13. Customer Facts và AI

### Đã làm

- Tạo fact thủ công qua API.
- Lưu budget_max, preference và các fact tương tự.
- Confidence và is_verified.
- Gắn nguồn message/order.
- Extractor nhận diện fact từ nội dung hội thoại.
- Có rule recommendation ở mức nền tảng.
- Có bảng experimentation và recommendation measurement.

### Còn thiếu

- Review queue cho fact AI tự trích xuất.
- Gộp fact trùng.
- Lịch sử sửa fact.
- Quy tắc hết hạn fact.
- Che dữ liệu nhạy cảm trước khi đưa vào model.
- Thu thập dữ liệu huấn luyện có consent.
- Supervised ML.
- A/B testing đầy đủ.
- Contextual bandit/RL có offline evaluation và guardrail.

---

## 14. Những gì đã kiểm chứng

- Backend test gần nhất: 156 passed, 6 warnings.
- Frontend test gần nhất: 12 passed.
- Backend compileall đã chạy thành công.
- Docker Compose build/start đã chạy trên Windows.
- Alembic đã upgrade tới 20260904_0022.
- Health endpoint trả status ok.
- Facebook webhook verification trả challenge đúng.
- Telegram webhook nhận tin và tạo conversation/message.
- Workflow Telegram tự gắn tag.
- Customer timeline trả message event.
- Customer fact tạo và đọc lại được.
- Tài liệu RAG indexing tới ready.
- Channel Facebook, Instagram, Telegram và Zalo Bot đã có record theo business ở môi trường kiểm thử.

Các warning chưa phải blocker:

- FastAPI on_event deprecated.
- anyio BlockingPortal deprecated.
- google.generativeai deprecated.
- Gemini quota cần cơ chế vận hành bền hơn.

---

## 15. Các lỗi vận hành đã gặp

1. Docker Compose báo thiếu backend/.env. Cần tạo file môi trường từ mẫu, không commit file thật.
2. Chạy compose từ sai thư mục làm báo no configuration file provided.
3. Chạy Alembic khi backend chưa chạy hoặc không ở đúng working directory.
4. Chạy script Python trong container nhưng thiếu PYTHONPATH/app context.
5. PowerShell curl là alias của Invoke-WebRequest; dùng curl.exe để kiểm tra HTTP.
6. Body JSON phải được tạo bằng ConvertTo-Json -Compress.
7. Volume Docker trên PowerShell phải dùng đường dẫn tuyệt đối.
8. Telegram setWebhook trả 404 nếu ghép bot token sai URL.
9. Zalo webhook trả 401 nếu secret header không giống secret đã đăng ký.
10. Ngrok domain cố định vẫn offline nếu tunnel không chạy.
11. Instagram outbound cần recipient ID dạng Instagram Scoped ID.
12. Account Facebook/Instagram khách vãng lai phụ thuộc quyền Meta; CRM có thể hiển thị record nhưng webhook gửi tin có thể bị Meta từ chối.
13. Media provider URL có thể hết hạn; cần proxy và fallback.
14. Không dùng reset database để sửa lỗi ứng dụng vì sẽ mất dữ liệu CRM.

---

## 16. Bảo mật bắt buộc

- Rotate toàn bộ token/API key đã từng xuất hiện trong terminal hoặc chat.
- Không đưa token, password, META_APP_SECRET, bot token, webhook secret hoặc database password vào Git.
- Giữ backend/.env trong .gitignore.
- Xóa credential legacy trong app_settings sau khi channel credential mã hóa đã dùng ổn định.
- Kiểm tra Git history trước khi public repository.
- Giới hạn CORS khi deploy production.
- Dùng HTTPS cho webhook.
- Kiểm tra chữ ký/secret webhook.
- Log phải che token và password.
- Audit việc xem, sửa, export và xóa dữ liệu khách hàng.

---

## 17. Roadmap ưu tiên

### P0 — An toàn để chạy thật

- Rotate secret.
- Dọn credential legacy.
- Kiểm tra Git history.
- Production CORS, HTTPS, rate limit và log redaction.
- Backup/restore PostgreSQL.

### P1 — CRM lõi

1. Customer 360 hoàn chỉnh:
   - Tag UI.
   - Segment.
   - Duplicate suggestion.
   - Merge confirmation.
   - Split/undo.
   - Timeline đầy đủ.

2. Sales và Purchase Order:
   - Supplier.
   - Line item.
   - Receiving một phần.
   - Inventory.
   - Payment.
   - Liên kết dịch vụ chatbot và đơn khách cuối.

3. Auth/RBAC production:
   - Invite.
   - Reset password.
   - Session rotation.
   - Permission theo module.
   - Audit đầy đủ.

4. Workflow vận hành thật:
   - Worker.
   - Queue.
   - Scheduler.
   - Retry/backoff.
   - Idempotency.
   - SLA reminder.

5. Báo cáo:
   - Revenue by channel.
   - Agent performance.
   - Funnel conversion.
   - Attribution.
   - Dashboard drill-down.

6. RAG:
   - SDK mới.
   - Reindex worker.
   - Quota retry.
   - Provider fallback.
   - Evaluation set.
   - Citation/source.

### P2 — AI nâng cao và tối ưu

- Rule recommendation có giải thích.
- Fact extraction có review.
- Supervised ML.
- A/B testing.
- Contextual bandit.
- RL chỉ sau khi có dữ liệu, offline evaluation và giới hạn an toàn.
- Dự đoán churn, next best action và lead scoring.

---

## 18. Quy trình giao task cho người khác

Nhánh tích hợp là crm-completion. Mỗi phần mới phải dùng feature branch riêng, không sửa trực tiếp main.

Tên nhánh đề xuất:

- feat/customer-360-final.
- feat/purchase-order-ops.
- feat/auth-production.
- feat/workflow-worker.
- feat/reports-attribution.
- feat/rag-hardening.
- feat/ai-fact-review.

Cách tạo nhánh từ code hiện tại:

    git fetch origin
    git switch -c feat/customer-360-final origin/crm-completion

Nếu cần worktree riêng:

    git worktree add ..\smh-customer-360 -b feat/customer-360-final origin/crm-completion

Mỗi task phải có:

1. Mục tiêu nghiệp vụ.
2. API/model/UI nằm trong phạm vi.
3. File được phép sửa.
4. Migration cần tạo.
5. Test bắt buộc.
6. Tiêu chí nghiệm thu.
7. Không reset database.
8. Không sửa secret.
9. Không sửa ngoài phạm vi.

Sau khi làm xong:

    git add -A
    git commit -m "feat: one focused CRM change"
    git push -u origin feat/customer-360-final

Tạo Pull Request từ feature branch vào crm-completion. Sau khi review:

    git switch crm-completion
    git pull --ff-only origin crm-completion
    git merge --no-ff feat/customer-360-final
    docker compose run --rm backend python -m pytest tests -q
    git push origin crm-completion

Không dùng git reset --hard, force push hoặc xóa database để xử lý conflict. Hai khu vực dễ conflict nhất là frontend/src/App.vue và Alembic migration numbers.

---

## 19. Tiêu chuẩn hoàn thành một task

Một task chỉ được merge khi:

- Có test regression.
- Không phá tenant isolation.
- Không vượt quyền role.
- Migration chạy từ 20260904_0022 lên head mới.
- Backend test liên quan pass.
- Frontend build/test liên quan pass.
- Có kiểm tra API bằng dữ liệu tenant khác.
- Không có secret trong diff hoặc log.
- Có mô tả rollback.
- Có screenshot hoặc mô tả UI nếu task có frontend.
- Pull Request chỉ tập trung một nhóm nghiệp vụ.

---

## 20. Kết luận bàn giao

Nền tảng CRM hiện đã có đủ các khối chính: inbox đa kênh, Customer 360, customer identity, customer facts, tag, merge, product, sales order, purchase order cơ bản, lead pipeline, ticket/SLA, team/RBAC, workflow, báo cáo, RAG, auto-reply và media.

Phần còn lại chủ yếu là đưa các khối nền tảng này lên mức production: hoàn thiện nghiệp vụ tồn kho và thanh toán, làm worker/scheduler, nâng cấp báo cáo, làm RAG bền vững, bổ sung bảo mật và sau cùng mới huấn luyện ML/A-B/Bandit.

Tệp này không thay thế test hoặc migration. Khi code thay đổi, phải cập nhật test, migration và tài liệu bàn giao cùng Pull Request.

---

## 21. P1-02 đã triển khai trên nhánh crm-completion

P1-02 Sales và Purchase Operations đã được hoàn thiện ở mức nghiệp vụ lõi: supplier, snapshot đơn, vòng đời Sales Order, nhận hàng Purchase Order, ledger tồn kho, payment/refund, order events, timeline Customer 360 và báo cáo tồn/chi phí. Giao diện CRM đã có thao tác xác nhận đơn, cảnh báo tồn, thu/hoàn tiền, nhận hàng và thanh toán công nợ.

Migration hiện tại là `20260906_0024`. Bằng chứng kiểm thử và lệnh chạy Docker nằm trong `docs/superpowers/plans/2026-09-06-p1-02-sales-purchase-ops-verification.md`.

Các giới hạn còn lại của P1-02 là tích hợp cổng thanh toán bên ngoài, form receipt theo từng dòng và smoke test trên Docker/production; không nên đánh đồng các giới hạn này với việc xóa dữ liệu hoặc reset database.
