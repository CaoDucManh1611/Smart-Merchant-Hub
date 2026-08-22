# Thiết kế cơ sở dữ liệu và Use Case - Smart Merchant Hub

Tài liệu này là phần thiết kế bám theo code hiện tại của project `Smart-Merchant-Hub` và định hướng trong file Word `do-an-chuyen-luan-tot-nghiep-khoa-cntt-2025.docx`.

## 1. Phân biệt nguồn yêu cầu

### 1.1. Quy định lấy từ file Word

File Word đang đóng vai trò khung hướng dẫn/định hướng khóa luận, không phải đặc tả đầy đủ của code. Các nội dung cần giữ khi đưa phần này vào khóa luận:

- Đề tài: nền tảng CRM và Chatbot AI/RAG đa kênh cho nhiều doanh nghiệp.
- Các kênh trong phạm vi: Facebook Messenger, Instagram, TikTok Shop và Shopee.
- Các tác nhân: quản trị viên nền tảng, nhân viên hỗ trợ nền tảng, quản trị viên doanh nghiệp, nhân viên CSKH, khách hàng, kênh tích hợp và cổng thanh toán.
- Các nhóm nghiệp vụ: đăng ký, gói dịch vụ, thanh toán/gia hạn, quản lý nhân viên, kết nối kênh, quản lý khách hàng/hội thoại, kho tri thức, Chatbot AI, chuyển giao hội thoại và báo cáo.
- Quy định trình bày: Times New Roman, khổ A4, lề trái 3,5 cm; phải/trên/dưới 2,5 cm; tiêu đề bảng đặt phía trên, tiêu đề hình đặt phía dưới.

Tài liệu Word cũng ghi rõ các chi tiết nội bộ của Vpage không được tự suy đoán. Vì vậy, mô hình dưới đây là mô hình đề xuất cho **Smart Merchant Hub**, không phải mô hình nội bộ của Vpage.

### 1.2. Yêu cầu trực tiếp của người dùng

- Đọc project và tài liệu Word.
- Thiết kế khoảng 15-20 bảng có liên hệ với code.
- Gắn các bảng với Use Case hệ thống.
- Tạo sơ đồ cơ sở dữ liệu và các sơ đồ phục vụ phần phân tích/thiết kế.

## 2. Đối chiếu với code hiện tại

Code hiện tại đã có các luồng chính sau:

| Nhóm chức năng | Thành phần code | Dữ liệu đang dùng |
|---|---|---|
| Webhook đa kênh | `api/facebook.py`, `api/instagram.py`, `api/shopee.py`, `api/tiktok.py` | `customers`, `conversations`, `messages` |
| CRM hội thoại | `api/conversations.py` | `customers`, `conversations`, `messages` |
| Meta OAuth | `api/meta_oauth.py`, `services/meta_config_service.py` | `app_settings` |
| Kho tri thức | `api/documents.py`, `services/ingestion_service.py` | `documents`, `document_chunks` |
| Chatbot/RAG | `api/chat.py`, `services/auto_reply_service.py`, `rag/*` | `document_chunks`, `messages`, `app_settings`; log RAG hiện lưu JSONL |
| Giao diện | `frontend/src/App.vue` | inbox, upload tài liệu, RAG chat, Meta settings |

Mô hình mới giữ nguyên các bảng đang được query trực tiếp. Các cột tenant mới được để nullable trong giai đoạn chuyển đổi để không làm hỏng luồng webhook single-shop hiện tại.

## 3. Danh sách 20 bảng mục tiêu

`app_settings` là bảng cấu hình hệ thống đã có sẵn. 19 bảng còn lại được dùng để đưa project từ mô hình single-shop hiện tại lên mô hình nhiều doanh nghiệp theo tài liệu Word.

| STT | Bảng | Nhóm | Mục đích | Trạng thái trong code |
|---:|---|---|---|---|
| 1 | `app_settings` | Cấu hình | Token Meta, OAuth state, bật/tắt auto-reply | Đã có và đang dùng |
| 2 | `businesses` | Tenant | Hồ sơ doanh nghiệp sở hữu dữ liệu | Đã thêm model |
| 3 | `users` | Tài khoản | Quản trị viên, nhân viên CSKH, nhân viên hỗ trợ | Đã thêm model |
| 4 | `service_plans` | Thuê bao | Danh sách gói dịch vụ và giới hạn sử dụng | Đã thêm model |
| 5 | `subscriptions` | Thuê bao | Gói đang đăng ký và thời hạn của doanh nghiệp | Đã thêm model |
| 6 | `payments` | Thuê bao | Giao dịch đăng ký/gia hạn | Đã thêm model |
| 7 | `channels` | Tích hợp | Facebook, Instagram, TikTok Shop, Shopee của từng doanh nghiệp | Đã thêm model |
| 8 | `channel_events` | Tích hợp | Inbox webhook, chống xử lý trùng, theo dõi lỗi đồng bộ | Đã thêm model |
| 9 | `customers` | CRM | Hồ sơ khách hàng cuối theo kênh | Đã có, bổ sung tenant/contact |
| 10 | `conversations` | CRM | Hội thoại tập trung, trạng thái, độ ưu tiên, người phụ trách | Đã có, bổ sung tenant/assignment |
| 11 | `conversation_assignments` | CRM | Lịch sử phân công và chuyển giao | Đã thêm model |
| 12 | `messages` | CRM | Tin inbound/outbound, media, raw payload, trạng thái gửi | Đã có, bổ sung sender/status |
| 13 | `tags` | CRM | Nhãn nghiệp vụ như cần gọi lại, đơn hàng, khiếu nại | Đã thêm model |
| 14 | `conversation_tags` | CRM | Gắn nhiều nhãn cho một hội thoại | Đã thêm model |
| 15 | `products` | Bán hàng | Sản phẩm được tư vấn trong hội thoại | Đã thêm model |
| 16 | `orders` | Bán hàng | Đơn hình thành trong quá trình tư vấn | Đã thêm model |
| 17 | `order_items` | Bán hàng | Chi tiết sản phẩm trong đơn | Đã thêm model |
| 18 | `documents` | Tri thức | File nguồn của kho tri thức | Đã có, bổ sung tenant |
| 19 | `document_chunks` | Tri thức | Đoạn văn và vector embedding phục vụ RAG | Đã có |
| 20 | `chatbot_configs` | AI | Cấu hình Chatbot theo doanh nghiệp | Đã thêm model |

### 3.1. Khóa chính và khóa ngoại chính

| Bảng | Khóa chính | Khóa ngoại quan trọng |
|---|---|---|
| `businesses` | `id` | - |
| `users` | `id` | `business_id -> businesses.id` |
| `service_plans` | `id` | - |
| `subscriptions` | `id` | `business_id -> businesses.id`, `plan_id -> service_plans.id` |
| `payments` | `id` | `business_id -> businesses.id`, `subscription_id -> subscriptions.id` |
| `channels` | `id` | `business_id -> businesses.id` |
| `channel_events` | `id` | `channel_id -> channels.id` |
| `customers` | `id` | `business_id -> businesses.id` |
| `conversations` | `id` | `business_id`, `customer_id`, `channel_id`, `assigned_user_id` |
| `conversation_assignments` | `id` | `conversation_id`, `user_id`, `assigned_by` |
| `messages` | `id` | `conversation_id`, `sender_user_id` |
| `tags` | `id` | `business_id` |
| `conversation_tags` | `id` | `conversation_id`, `tag_id`, `created_by` |
| `products` | `id` | `business_id` |
| `orders` | `id` | `business_id`, `customer_id`, `conversation_id` |
| `order_items` | `id` | `order_id`, `product_id` |
| `documents` | `id` | `business_id` |
| `document_chunks` | `id` | `document_id` |
| `chatbot_configs` | `id` | `business_id` (unique, 1-1) |

### 3.2. Từ điển dữ liệu rút gọn

| Bảng | Các cột nghiệp vụ chính |
|---|---|
| `app_settings` | `key` PK, `value` |
| `businesses` | `id` PK, `name`, `slug` UK, `email`, `phone`, `address`, `status`, `created_at`, `updated_at` |
| `users` | `id` PK, `business_id` FK, `full_name`, `email`, `password_hash`, `role`, `is_active`, timestamps; unique `(business_id, email)` |
| `service_plans` | `id` PK, `code` UK, `name`, `description`, `price`, `billing_cycle`, `max_users`, `max_channels`, `max_documents`, `features`, `status` |
| `subscriptions` | `id` PK, `business_id` FK, `plan_id` FK, `status`, `starts_at`, `ends_at`, `auto_renew`, `created_at` |
| `payments` | `id` PK, `business_id` FK, `subscription_id` FK, `amount`, `currency`, `provider`, `provider_transaction_id` UK, `status`, `paid_at`, `raw_response` |
| `channels` | `id` PK, `business_id` FK, `channel_type`, `name`, `external_account_id`, `access_token`, `status`, `config`, connection timestamps; unique `(business_id, channel_type, external_account_id)` |
| `channel_events` | `id` PK, `channel_id` FK, `event_type`, `external_event_id`, `payload`, `status`, `error_message`, `received_at`, `processed_at`; unique `(channel_id, external_event_id)` |
| `customers` | `id` PK, `business_id` FK nullable, `channel`, `external_user_id`, `name`, `email`, `phone`, `address`, `avatar_url`, timestamps; unique `(business_id, channel, external_user_id)` |
| `conversations` | `id` PK, `business_id` FK nullable, `customer_id` FK, `channel_id` FK nullable, legacy `channel`, `status`, `priority`, `assigned_user_id`, `last_message_at`, `closed_at`, timestamps |
| `conversation_assignments` | `id` PK, `conversation_id` FK, `user_id` FK, `assigned_by` FK nullable, `assignment_type`, `assigned_at`, `unassigned_at` |
| `messages` | `id` PK, `conversation_id` FK, `sender_type`, `sender_user_id` FK nullable, `channel`, external IDs, `direction`, `content`, media fields, `raw_payload`, `status`, `metadata`, `received_at`, `sent_at` |
| `tags` | `id` PK, `business_id` FK, `name`, `color`, `created_at`; unique `(business_id, name)` |
| `conversation_tags` | `id` PK, `conversation_id` FK, `tag_id` FK, `created_by` FK nullable, `created_at`; unique `(conversation_id, tag_id)` |
| `products` | `id` PK, `business_id` FK, `sku`, `name`, `description`, `price`, `stock_quantity`, `status`, `metadata`, timestamps; unique `(business_id, sku)` |
| `orders` | `id` PK, `business_id` FK, `customer_id` FK, `conversation_id` FK nullable, `order_number`, `status`, `total_amount`, shipping fields, `metadata`, timestamps; unique `(business_id, order_number)` |
| `order_items` | `id` PK, `order_id` FK, `product_id` FK, `quantity`, `unit_price`, `line_total` |
| `documents` | `id` PK, `business_id` FK nullable, `filename`, `file_type`, `file_size`, `status`, `chunk_count`, `error_message`, `uploaded_at`, `processed_at` |
| `document_chunks` | `id` PK, `document_id` FK, `content`, `chunk_index`, `embedding` vector, `metadata`, `created_at` |
| `chatbot_configs` | `id` PK, `business_id` FK UK, `name`, `enabled`, `handoff_enabled`, `system_prompt`, `top_k`, `similarity_threshold`, `allowed_channels`, timestamps |

## 4. Mối quan hệ nghiệp vụ

- Một `business` có nhiều `users`, `channels`, `customers`, `conversations`, `documents`, `products`, `orders` và một `chatbot_config`.
- Một `channel` có nhiều `channel_events`; mỗi event được định danh bởi `channel_id + external_event_id` để hỗ trợ idempotency.
- Một `customer` có nhiều `conversations` và `orders`.
- Một `conversation` có nhiều `messages`, nhiều lịch sử `conversation_assignments`, nhiều `conversation_tags` và có thể phát sinh `orders`.
- Một `document` có nhiều `document_chunks`. `document_chunks.embedding` tiếp tục dùng `pgvector` như code hiện tại.
- Một `subscription` tham chiếu một `service_plan` và có nhiều `payments` để phục vụ đăng ký/gia hạn.
- Một `product` có thể xuất hiện trong nhiều `order_items`; một `order` có nhiều `order_items`.

## 5. Use Case hệ thống

### 5.1. Tác nhân

| Mã | Tác nhân | Vai trò |
|---|---|---|
| A1 | Quản trị viên nền tảng | Quản lý doanh nghiệp, gói dịch vụ, thuê bao và báo cáo tổng quan |
| A2 | Nhân viên hỗ trợ nền tảng | Hỗ trợ doanh nghiệp trong quá trình cấu hình/sử dụng |
| A3 | Quản trị viên doanh nghiệp | Quản lý doanh nghiệp, nhân viên, kênh, tri thức, Chatbot và báo cáo |
| A4 | Nhân viên CSKH | Xem khách hàng, nhận hội thoại, phản hồi, phân công, tạo đơn |
| A5 | Khách hàng | Gửi yêu cầu qua kênh tích hợp và nhận tư vấn |
| A6 | Kênh tích hợp | Gửi webhook/event và nhận tin outbound |
| A7 | Cổng thanh toán | Xử lý giao dịch đăng ký hoặc gia hạn |

### 5.2. Danh sách Use Case và bảng tham gia

| Mã UC | Use Case | Tác nhân chính | Bảng chính |
|---|---|---|---|
| UC01 | Đăng ký sử dụng giải pháp | A3 | `businesses`, `users`, `service_plans`, `subscriptions` |
| UC02 | Đăng nhập và phân quyền | A1, A2, A3, A4 | `users`, `businesses` |
| UC03 | Lựa chọn gói dịch vụ | A3 | `service_plans`, `subscriptions` |
| UC04 | Thanh toán dịch vụ | A3, A7 | `subscriptions`, `payments` |
| UC05 | Gia hạn dịch vụ | A3, A7 | `subscriptions`, `payments` |
| UC06 | Quản lý nhân viên | A3 | `users` |
| UC07 | Kết nối/quản lý kênh | A3, A6 | `channels`, `channel_events`, `app_settings` |
| UC08 | Tiếp nhận webhook và chuẩn hóa dữ liệu | A6 | `channel_events`, `customers`, `conversations`, `messages` |
| UC09 | Quản lý khách hàng | A3, A4 | `customers`, `conversations`, `orders` |
| UC10 | Tiếp nhận yêu cầu khách hàng | A4, A5 | `customers`, `conversations`, `messages` |
| UC11 | Tư vấn và phản hồi khách hàng | A4, A5 | `messages`, `products`, `orders`, `order_items` |
| UC12 | Phân công/chuyển giao hội thoại | A3, A4, Chatbot | `conversations`, `conversation_assignments`, `users` |
| UC13 | Gắn nhãn và theo dõi lịch sử | A4 | `tags`, `conversation_tags`, `messages` |
| UC14 | Quản trị tri thức doanh nghiệp | A3 | `documents`, `document_chunks` |
| UC15 | Cấu hình Chatbot AI | A3 | `chatbot_configs`, `documents`, `document_chunks` |
| UC16 | Chat RAG và tự động trả lời | A5, A4, Chatbot | `chatbot_configs`, `document_chunks`, `conversations`, `messages` |
| UC17 | Theo dõi báo cáo | A1, A3 | truy vấn tổng hợp từ CRM, bán hàng, thuê bao |

### 5.3. Đặc tả ngắn các UC quan trọng

#### UC07 - Kết nối/quản lý kênh

- **Tiền điều kiện:** doanh nghiệp đã có tài khoản và gói dịch vụ còn hiệu lực.
- **Dòng chính:** quản trị viên chọn kênh -> xác thực OAuth/API -> lưu tài khoản ngoài -> kiểm tra trạng thái webhook -> đưa kênh vào hoạt động.
- **Dòng thay thế:** token hết hạn hoặc webhook đăng ký thất bại -> lưu trạng thái lỗi, không nhận kênh là active.
- **Bảng:** `channels`, `channel_events`, `app_settings`.
- **Code hiện tại:** Meta OAuth đang lưu thông tin tương thích trong `app_settings`; bảng `channels` là lớp chuẩn hóa để hỗ trợ nhiều doanh nghiệp/kênh ở bước tiếp theo.

#### UC08 - Tiếp nhận webhook và chuẩn hóa dữ liệu

- **Tiền điều kiện:** kênh đang active và webhook có payload hợp lệ.
- **Dòng chính:** nhận event -> ghi `channel_events` -> kiểm tra `external_event_id` -> chuẩn hóa sender/message -> upsert `customers` -> tìm/tạo `conversations` -> ghi `messages` -> kích hoạt auto-reply nếu bật.
- **Dòng thay thế:** event trùng -> không ghi message lần hai; payload sai -> đánh dấu event error và trả response an toàn.
- **Code hiện tại:** `message_service.py` đã có chuẩn hóa Facebook/Instagram và chống trùng message qua `external_message_id`.

#### UC14 - Quản trị tri thức doanh nghiệp

- **Tiền điều kiện:** người dùng có quyền quản trị doanh nghiệp.
- **Dòng chính:** upload file -> tạo `documents` pending -> load/chunk/embed -> lưu `document_chunks` -> chuyển status ready.
- **Dòng thay thế:** file không hỗ trợ hoặc ingestion lỗi -> status error và lưu `error_message`.
- **Code hiện tại:** đã có đầy đủ upload, background ingestion, chunking, embedding, truy vấn chunk và xóa tài liệu.

#### UC16 - Chat RAG và tự động trả lời

- **Dòng chính:** nhận câu hỏi -> xác định doanh nghiệp/kênh -> retrieve top-k chunk -> build prompt -> gọi LLM -> trả nguồn -> ghi outbound message.
- **Dòng thay thế:** không có context hoặc cần người xử lý -> không tự trả lời và chuyển hội thoại cho nhân viên.
- **Code hiện tại:** `/api/chat`, `/api/chat/stream` và `process_rag_auto_reply` đã triển khai pipeline; log chi tiết vẫn ở `rag_runs.jsonl`, không tính là bảng thứ 21.

## 6. Sơ đồ/luồng tham chiếu

- ERD: [diagrams/erd.mmd](diagrams/erd.mmd)
- Use Case hệ thống: [diagrams/system-use-case.mmd](diagrams/system-use-case.mmd)
- Luồng tiếp nhận và xử lý hội thoại: [diagrams/conversation-flow.mmd](diagrams/conversation-flow.mmd)
- Luồng RAG/auto-reply: [diagrams/rag-flow.mmd](diagrams/rag-flow.mmd)
- Script chạy trực tiếp trên DBeaver: [schema-20-tables-dbeaver.sql](schema-20-tables-dbeaver.sql)

Khi đưa vào Word, đặt caption hình phía dưới hình theo mẫu `Hình 3.x: ...`, caption bảng phía trên bảng theo mẫu `Bảng 3.x: ...`. Để xuất sơ đồ thành ảnh, có thể dán mã Mermaid vào Mermaid Live Editor hoặc công cụ hỗ trợ Mermaid rồi chèn PNG/SVG vào Chương 2/3.

## 7. Phạm vi triển khai hiện tại và phần cần nối tiếp

Đã triển khai trong code:

- 14 model/table mới cho multi-tenant, billing, channel, CRM assignment/tag, sales và chatbot config.
- Mở rộng model `customers`, `conversations`, `messages`, `documents` với các cột liên quan tenant/contact/assignment/status.
- `init_db()` tạo các bảng mới và migration tương thích cho database cũ.
- Giữ `business_id` nullable trong giai đoạn chuyển đổi vì webhook hiện tại đang chạy theo cấu hình single-shop trong `.env`/`app_settings`.

Phần cần nối tiếp nếu muốn chạy đầy đủ multi-tenant production:

- Thêm middleware xác định `business_id` từ JWT/session.
- Khi kết nối OAuth, tạo bản ghi `channels` thay vì chỉ lưu token vào `app_settings`.
- Webhook ghi `channel_events`, tìm `channel_id` và gán `business_id` trước khi ghi CRM.
- Thêm API CRUD cho `users`, `products`, `orders`, `tags`, `subscriptions` và `payments`.
- Đổi truy vấn RAG thành lọc theo `documents.business_id` để bảo đảm tách dữ liệu tuyệt đối giữa các doanh nghiệp.
