# 17 - Feedback artifacts và human review

Ngày: 2026-11-04. Chỉ xuất/review artifact, không tự import KB hoặc train.

## Phạm vi ghi

- Bổ sung `backend/scripts/export_rag_faq_candidates.py`.
- Thêm `backend/scripts/review_rag_feedback.py`.
- Thêm test riêng `backend/tests/test_rag_feedback_artifacts_isolated.py`.
- Không sửa test exporter cũ, models, config, auto_reply hoặc graph. Không thay đổi nội dung dữ liệu sản xuất.

## Export tương thích

Giữ nguyên `pair_handoff_turn(messages, handoff_created_at, question_message_id=None)` và tám cột CSV đầu:

```text
business_id, conversation_id, question_message_id, staff_message_id,
question, staff_answer, source_handoff_reason, review_status
```

Exporter tiếp tục lấy handoff đã có staff reply cùng lượt. Không tự coi bot answer là correction, không mượn câu trả lời từ lượt sau. Conversation phải có business đúng, không fallback business null sang tenant caller.

Các cột bổ sung: `schema_version`, `candidate_id`, `content_hash`, `bot_message_ids`, `run_ids`, `source_refs`, `error_types`, `routes`, `provenance`, `synthetic`. Các trường danh sách là chuỗi JSON trong CSV. `review_status` luôn **`pending_human_review`**, kể cả metadata nguồn chứa trạng thái khác.

Provenance chỉ lấy bot messages cùng conversation, nằm giữa question và staff reply đã ghép. Lưu ID message, business/conversation, run/correlation IDs, reference IDs, mã lỗi và route có trong metadata. Metadata không có trace thì danh sách để rỗng; không bịa run/source. Chỉ allowlist reference IDs/source_kind và mã có cấu trúc; không xuất raw_payload, raw exception, prompt, filename/URL hoặc dictionary metadata tùy ý. Cờ synthetic/test của question, staff, bot hoặc handoff được giữ thành cờ chặn review.

`content_hash` là SHA-256 của canonical JSON chứa tất cả cột nội dung/provenance theo schema, trừ `candidate_id`, `content_hash`, `review_status`. `candidate_id = "faq-" + content_hash`. Không đưa thời điểm export vào hash, nên re-export cùng evidence và CSV roundtrip giữ ID ổn định. Đổi question/staff correction/tenant/trace sẽ đổi hash và ID. Hash là kiểm tra nội dung, không phải chữ ký xác thực.

## API chính xác

```python
candidate_content_hash(candidate: dict) -> str

build_candidate(
    business_id: int, conversation_id: int, question, staff,
    messages, handoff_metadata: dict | None = None,
) -> dict[str, str]

collect_candidates(business_id: int | None = None) -> list[dict[str, str]]

review_candidates(
    candidates: list[dict], decisions: list[dict], business_id: int,
    now: datetime | None = None,
) -> list[dict]
```

`collect_candidates()` và CLI cũ `--output` giữ cách gọi. `--business-id` mới cho phép xuất riêng shop để review. DB sessions/models của exporter được import lazy chỉ khi thực sự collect, nên import helper/review không khởi tạo settings hoặc DB engine.

## Decisions và seed

Review đọc candidates CSV và decisions JSONL. Mỗi decision phải có các trường sau do người duyệt điền:

```json
{
  "candidate_id": "faq-<hash from current candidate>",
  "content_hash": "<hash from current candidate>",
  "business_id": 1,
  "decision": "approved",
  "reviewer_type": "human",
  "reviewer": "<real staff identity>",
  "reviewed_at": "<ISO timestamp with timezone>",
  "corrected_answer": "<optional human correction>"
}
```

`decision` chỉ nhận `approved` hoặc `rejected`; không có decision thì không có seed. `corrected_answer` có thể bỏ để dùng staff_answer. Timestamp bắt buộc có timezone và không nằm trong tương lai. Chặn reviewer rỗng/thiếu, AI-only, candidate tự đổi trạng thái approved, stale content/hash/ID, candidate hoặc decision khác shop, nested provenance khác shop/conversation và synthetic/test flags. Duplicate candidate hoặc decision mâu thuẫn làm cả batch fail.

Output JSONL chỉ gồm câu đã human-approved, giữ business, candidate/hash, reviewer/timestamp và source provenance. File candidates luôn pending và không bị sửa. Nếu một input không hợp lệ thì validate thất bại trước khi ghi output. Output không được trùng đường dẫn candidates/decisions. Diagnostic không in nội dung input hoặc raw metadata.

Ví dụ CLI, **chưa chạy trên dữ liệu thật**:

```powershell
python backend/scripts/export_rag_faq_candidates.py --business-id 1 --output <shop-candidates.csv>
python backend/scripts/review_rag_feedback.py --candidates <shop-candidates.csv> --decisions <human-decisions.jsonl> --business-id 1 --output <approved-seed.jsonl>
```

Review yêu cầu file scoped đúng một shop; file mixed-tenant bị từ chối, không tự chia hoặc bỏ qua record khác shop. `reviewer_type=human` và danh tính là attestation trong artifact: công cụ offline không xác thực tài khoản người duyệt. Vận hành vẫn phải xác minh người duyệt và quyền/consent trước khi import; không coi chuỗi metadata là bằng chứng đăng nhập. Artifact không phải training/KB import tự động.

## Kiểm chứng và ranh giới

Lệnh chung với memory:

```powershell
python -m pytest -q -s backend/tests/test_conversation_memory_isolated.py backend/tests/test_rag_feedback_artifacts_isolated.py backend/tests/test_rag_faq_candidate_export.py -p no:cacheprovider
```

- Giữ conftest mặc định và `RUN_POSTGRES_TESTS` mặc định. Memory fixtures thực tế chạy **PostgreSQL trong schema test riêng**, dù URL fixture viết SQLite. Artifact tests chỉ xử lý objects/CSV/JSONL tạm; không collect production hoặc gọi dịch vụ ngoài.
- Lượt default đầu: **90 passed in 36.28s**. Bao gồm test exporter cũ nguyên vẹn, hash/CSV compatibility, provenance same-turn và allowlist, human approval, reject AI-only/crossshop/stale/synthetic, duplicate decisions, CLI output, và subprocess xác nhận review import không load settings/DB.
- Lượt sơ bộ `--noconftest` là SQLite thật với **89 passed**, không dùng để mô tả engine của harness mặc định. Kết quả lượt cuối được bổ sung bên dưới.
- Không chạy exporter trên DB thật, không tạo human approval giả cho dữ liệu thật, không đọc/in raw secrets, không import/train, không server/Telegram, không commit/push. Các quyết định trong tests chỉ nằm trong fixture test.
