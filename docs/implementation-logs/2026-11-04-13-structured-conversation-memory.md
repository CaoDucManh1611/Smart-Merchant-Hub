# 13 - Memory hội thoại có cấu trúc

Ngày: 2026-11-04. Module độc lập, không migration và không ghi DB.

## Phạm vi ghi

- Thêm `backend/app/services/conversation_memory.py`.
- Thêm test riêng `backend/tests/test_conversation_memory_isolated.py`.
- Không sửa auto_reply, graph, models, config hoặc main wiring trong công việc này. Worktree có thay đổi từ trước và main đang tích hợp song song; không hoàn nguyên các thay đổi đó.

## API chính xác

```python
build_reply_memory(
    db: Session, business_id: int, conversation_id: int,
    query: str, answer: str, product_ids: list[int] | None = None,
    now: datetime | None = None,
) -> dict

load_reply_memory(
    db: Session, business_id: int, conversation_id: int,
    now: datetime | None = None,
) -> dict

resolve_memory_products(
    db: Session, business_id: int, conversation_id: int,
    current_text: str, now: datetime | None = None,
) -> list[Product]
```

Các đối số không keyword-only; có thể gọi positional hoặc keyword. `now` naive được hiểu là UTC; datetime aware được đổi sang UTC.

## State và hợp đồng

- `MEMORY_KEY = "reply_memory"`; `schema_version = 1`.
- `scope`: `business_id`, `customer_id`, `conversation_id` lấy từ conversation có business chính xác. Thiếu business/customer hợp lệ trả state rỗng, không mặc định tenant từ caller.
- `active_product_ids`: chỉ ID active thực sự được nêu bằng tên/alias hiển thị đầy đủ, duy nhất trong catalog shop. `product_ids` là bộ lọc thêm, không phải bằng chứng. `None` cho phép suy ra ID từ tên exact duy nhất; `[]` chủ động không lưu ID.
- Chỉ chuẩn hóa NFC, hoa/thường và whitespace khi match identity. Không bỏ dấu, sửa typo, fuzzy, match SKU đơn lẻ, keywords/search_terms hoặc mở rộng theo kích thước. Alias chỉ chứa kích thước kèm đơn vị cũng bị bỏ.
- Tên dài bao phủ span của tên ngắn: `A Plus` không kéo thêm `A`. Alias trùng giữa hai sản phẩm không xác định được ID, kể cả caller chỉ truyền một ID.
- `constraints`: chỉ ngân sách VND và số lượng được nói rõ trong query của lượt này. Không kế thừa ngầm constraint cũ. Ngân sách dạng `1,5 triệu`, `500k`, `500.000 đồng` được kiểm tra; số có dấu phân cách mơ hồ không được đoán.
- `pending_slot`: `budget`, `qty`, `variant`, `product` hoặc `None`, suy ra bảo thủ từ câu hỏi trong answer. `last_intent`: `other`, `reset`, `compare`, `stock`, `price`, `purchase`.
- `created_at`, `expires_at`: ISO UTC, TTL đúng 30 phút. Hết hạn tại đúng `expires_at`. Không lấy sent_at làm TTL thay thế khi metadata thiếu/hỏng.
- Không lưu query/answer thô, giá, kho hoặc snapshot facts trong state. Chuỗi intent `price`/`stock` chỉ là nhãn ý định.

`load_reply_memory` chỉ xét outbound bot/staff mới nhất. Reply phải `sent`, có `sent_at` hợp lệ, scope/schema/timestamps đúng. Reply mới failed/pending/không memory là barrier; không lùi xuống reply cũ còn TTL. Tối đa một inbound customer được phép xuất hiện sau reply đó. Các ID được đối chiếu lại với nội dung reply và catalog hiện hành; sản phẩm inactive, sai shop, ID không thực sự xuất hiện sẽ bị loại. Metadata không hợp lệ trả state rỗng; không phục hồi bằng fuzzy history.

`_catalog` dùng `select(...).execution_options(populate_existing=True)` để refresh cả ORM identity map. Lượt trả candidates dùng SQL filter `Product.status == "active"`; lượt chứng minh tính duy nhất xét catalog cùng shop, kể cả dòng inactive để tránh alias nhập nhằng. Conversation và outbound row cũng được refresh khi đọc scope/status.

`resolve_memory_products` chỉ trả candidates cho câu nối tiếp nhận diện được, ví dụ `Cái đó còn hàng không?`, `Loại nào rẻ hơn?`, **`Loại rẻ hơn còn bao nhiêu cái?`**. Tên/chủ đề mới, mã chưa biết, query dimension-only và reset explicit trả `[]`. Bộ nhận diện dùng whitelist bảo thủ; câu còn từ nội dung chưa nhận diện cũng trả `[]` để caller hỏi lại hoặc chạy resolver hiện tại. Nếu có hai ID thì trả cả hai, không tự chọn SKU; caller tính loại rẻ hơn từ giá/kho mới đọc.

## Điểm tích hợp cho main

Caller lấy query của đúng lượt, gọi `build_reply_memory` trước save rồi truyền:

```python
extra_metadata = {
    **(extra_metadata or {}),
    MEMORY_KEY: build_reply_memory(db, business_id, conversation_id, query, text),
}
```

Chỉ state ở outbound đã gửi thành công mới đọc lại được. `_previous_explicit_product_list` có thể gọi trực tiếp `resolve_memory_products(db, business_id, conversation_id, current_text)`. Không thêm dimension fallback khi helper trả rỗng. Main sở hữu phần wiring; công việc module này không gửi tin hoặc sửa đường gửi.

## Kiểm chứng và ranh giới

Lệnh targeted dùng **conftest mặc định**, không đổi `RUN_POSTGRES_TESTS`:

```powershell
python -m pytest -q -s backend/tests/test_conversation_memory_isolated.py backend/tests/test_rag_feedback_artifacts_isolated.py backend/tests/test_rag_faq_candidate_export.py -p no:cacheprovider
```

- Fixture khai báo SQLite URL nhưng conftest mặc định remap sang **PostgreSQL với schema test riêng**. Output kiểm chứng: `memory fixture actual dialect: postgresql`. Fixture tạo đủ bảng và dữ liệu FK; không dựa vào SQLite bỏ qua FK.
- Lượt default đầu: **90 passed in 36.28s**. Kết quả lượt cuối sau bổ sung kiểm tra được ghi bên dưới.
- Lượt sơ bộ trước khi nhận lưu ý về harness: `--noconftest`, chặn network và dùng SQLite in-memory thực tế, **89 passed**. Đây chỉ là kết quả module ban đầu, không đại diện harness PostgreSQL mặc định.
- Test gồm exact names cùng kích thước lốp không widen, alias trùng, ID hints sai tenant, expiry biên 30 phút chỉ từ metadata, reply mới không memory, failed status, quá một lượt cũ, metadata sai kiểu, scope customer thay đổi và refresh giá/kho/status ngoài ORM.
- Không chạy server, provider/embedding/Telegram hoặc production import. Lượt default chỉ dùng DB test do harness chuẩn bị; không phải xác nhận live chat. Không mở/in raw secrets; harness tự đọc cấu hình DB theo quy trình test có sẵn.
- Không commit/push.
