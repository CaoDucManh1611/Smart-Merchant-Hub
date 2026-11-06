# Tiếp tục RAG sau giới hạn sử dụng: audit trạng thái và tiến độ

Ngày 2026-11-04. Nhánh `codex/rag-rfm-all-updates-20261104`. Working tree dùng chung đang có thay đổi chưa commit; lượt này không commit/push, deploy, reindex dữ liệu thật, gọi provider hay gửi tin khách.

## Nguồn yêu cầu và trạng thái Git

- Đối chiếu lại đặc tả `Smart Merchant Hub — RAG Reliability, Vision & Intelligent Sales Assistant`: bảy phase từ độ chính xác/recovery, benchmark, latency/cost, vision, hội thoại tự nhiên, tư vấn có giới hạn đến benchmark multimodal.
- Đối chiếu `git status`, `git diff --stat`, các log 01–22 và code/test mới. Trước lượt sửa tiếp, Git có 23 file tracked thay đổi (2.026 dòng thêm, 373 dòng xóa) cùng các module/test/log untracked. Đây là working tree có sẵn; không xóa hoặc ghi đè phần không liên quan.
- Zeno để lại integration tám hạng mục và các sửa consent/memory trong log 20–21. Gauss để lại review độc lập log 18: implementation evidence 15/24, acceptance evidence 5/21 và bốn P1. Không coi các số pytest do agent báo lại là kiểm chứng độc lập.

## Phân loại theo đặc tả gốc

| Phạm vi | Trạng thái hiện tại | Bằng chứng / giới hạn |
| --- | --- | --- |
| Graph/RAG chung, catalog SQL có điều kiện | Đã triển khai offline | `rag/serving.py`, `services/catalog_search.py`, Graph và shortcut SQL; test filter trước LIMIT, tenant, SKU. Chưa replay adapter/live. |
| Claim Verification theo offering/SKU/variant | Đã triển khai offline | `rag/claim_verification.py`; giá catalog bắt buộc có `offering_refs`, đối chiếu current SQL row và không được tráo giữa sản phẩm. Chưa chấm answer production đa ngành. |
| Memory sản phẩm có TTL/topic barrier | Đã triển khai offline | `services/conversation_memory.py` chỉ đọc outbound gần nhất, TTL 30 phút, không lưu giá/kho. Calendar follow-up chỉ đọc tin inbound ngay trước trong TTL. Chưa replay live. |
| Consent cho feedback learning | Hoàn thiện thêm trong lượt này | Export/approval dùng purpose riêng `faq_reuse`, recheck current consent và opt-out. API tạo consent nay bắt buộc inbound customer evidence cho `faq_reuse`. Chưa có UI/policy vận hành cấp consent này. |
| Reindex transaction và quota reconciliation | Đang làm dở | Publish tenant atomic và recovery quota script đã có; lượt này sửa commit trên tenant session đã đóng. Chưa có versioned index snapshot để rollback sau một publish hợp lệ nhưng chất lượng xấu; chưa dry-run/reindex thật. |
| Structured output, bounded calls/fallback | Đã triển khai offline | Pydantic schema và turn budget có test fake SDK. Chưa thử provider staging/live, hard wall cancellation hoặc webhook-to-delivery p95. |
| Adaptive retrieval | Thử nghiệm, mặc định an toàn | BM25/PPR-off giữ mặc định; retry bounded và giữ hard filters. Chưa có benchmark người duyệt chứng minh hybrid/reranker tốt hơn. |
| Paired benchmark A/B | Hạ tầng đã có, kết quả chất lượng chưa có | `scripts/compare_rag_runs.py` khóa snapshot/question/model/config và fail closed với telemetry/label thiếu. Chưa có paired run đã duyệt nên không có quality PASS. |
| Vision image-to-catalog | Đang làm dở, flag mới mặc định tắt | Đường hiện hữu có mô tả ảnh, shortlist đúng tenant, so ảnh tham chiếu và SQL giá/kho; exact-code flag mặc định false. Lượt này thêm cache observation theo tenant + hash ảnh + model + loại phân tích, TTL ngắn, không lưu ảnh hay giá/kho. Chưa test provider/media adapter/multi-image live. |
| Human-like formatting | Một phần | Prompt yêu cầu ngắn/tự nhiên và nhiều SQL formatter có sẵn. Chưa có benchmark naturalness hoặc formatter toàn luồng đã chứng minh không đổi dữ kiện. |
| Autonomous sales consultation | Một phần, bị giới hạn quyền | Graph/catalog/recommendation/workflow xử lý nhiều nhu cầu và không tự tạo giao dịch thiếu xác nhận. Chưa có benchmark đa ngành chứng minh chọn tool/hỏi slot đúng. |
| Benchmark multimodal 15 nhóm | Chưa triển khai kết quả | Chưa có snapshot, nhãn người, replay provider và metrics image/SKU/grounding/naturalness/latency/cost. |

## Thay đổi của lượt tiếp tục

1. Thêm `faq_reuse` vào nhóm consent bắt buộc có tin nhắn inbound của customer; bổ sung regression API.
2. Sửa `recover_reindex_quota.py`: mọi tenant mutation được commit khi tenant session còn mở; không dùng session đã đóng ở nhánh `--abandon-stale`.
3. Thêm `image_observation_cache.py`: cache process-local có TTL và giới hạn kích thước, tách tenant/image/model/analysis; chỉ cache output nhận diện. Product row, price, stock và status vẫn query SQL mỗi lượt.
4. Nối cache vào image-to-catalog matcher; không đổi model/provider và không bật feature flag.

## Kiểm thử đã tự chạy trong lượt này

- Focused baseline trước sửa: **66 passed / 21,37 s**.
- Consent API + recovery helper sau sửa: **7 passed / 14,14 s**.
- Vision cache + image exact + channel auto-reply + consent + recovery: **82 passed / 15,23 s**.
- Bộ regression rộng gồm Graph/RAG, catalog search, safe reindex/recovery, memory, calendar TTL, turn budget, feedback consent/artifact isolation, channel auto-reply, image matching/cache, benchmark comparator và customer consent: **427 passed / 169,85 s**.
- Chạy lại riêng các file chịu ảnh hưởng trực tiếp sau thay đổi cuối: **100 passed / 14,64 s**.
- `git diff --check`: không có lỗi whitespace; Git chỉ cảnh báo hai file LF sẽ được đổi sang CRLF nếu Git ghi lại chúng trên Windows.

Các kết quả trên chứng minh contract code/fixture, không chứng minh RAG thông minh hơn. Không có provider call, benchmark answer có nhãn người, latency/cost production hoặc canary trong lượt này.

## Audit artifact đánh giá hiện có

- Hai file `rag-answer-human-review-*.csv` đều có **34/34 dòng `review_status=pending`** và không có reviewer.
- File `rag-answer-ai-adjudicated-gpt6-sol-v2.csv` có 34 dòng `ai_approved`, nhưng reviewer ghi rõ `GPT-6 Sol (AI auto-review; not a human reviewer)`. Không dùng file này làm bằng chứng quality gate người duyệt.
- Bộ retrieval mới nhất có 284 case, nhưng nhãn là `machine_verified_source_support` hoặc trạng thái máy tương tự. Bộ này hữu ích để regression retrieval, không thay thế chấm câu trả lời đầu-cuối.
- `compare_rag_runs.py` cố ý fail closed nếu thiếu nhãn người, snapshot/hash/question/model/config tương ứng. Vì vậy chưa thể tạo kết luận paired quality hợp lệ từ artifact hiện tại.

## Việc còn chặn nghiệm thu

1. Chốt thiết kế rollback versioned index hoặc quy trình phục hồi post-publish; không tự migration/reindex production.
2. Tạo paired run cùng snapshot/model/prompt và nhãn người; đo correctness, hard errors, helpfulness, Recall/NDCG khi có gold ranking, p50/p95, calls/token/cost.
3. Chạy staging vision/media adapter với bộ 15 nhóm, gồm ảnh mờ, nhiều vật, hai shop, follow-up và provider lỗi; flag vẫn off đến khi qua gate.
4. Đo naturalness và tool routing trên câu đa ngành; không suy quality từ pytest.
5. Sau cùng mới đề xuất canary từng shop, kèm ngưỡng đã chốt trước và rollback; lượt này chưa được phép bật.

## Kết luận nghiệm thu ở snapshot này

- **Code contract:** sạch trên phạm vi regression đã nêu.
- **Chất lượng RAG:** chưa được chứng minh tăng; không phát hành kết luận PASS.
- **Rollback reindex:** transaction hiện tại bảo vệ lỗi trước publish và coi publish là thành công sau commit. Muốn rollback một phiên bản đã publish nhưng quality kém cần schema/version snapshot hoặc quy trình backup/restore được phê duyệt; không thể giả lập an toàn chỉ bằng sửa helper hiện tại.
- **Dữ liệu/nhãn:** cần người duyệt hoặc quy trình review chính thức. Không tự đổi nhãn AI thành nhãn người.
- **Live/staging:** chưa xác minh; feature vision vẫn mặc định tắt, không gọi kênh thật.
