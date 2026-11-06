# RAG: rollback snapshot, benchmark ghép cặp, vision offline và multimodal gate

Ngày 2026-11-04. Nhánh `codex/rag-rfm-all-updates-20261104`. Working tree dùng chung được giữ nguyên; không commit, push, deploy, gọi provider, gửi tin khách, chạy migration hay reindex dữ liệu thật.

## 1. Kiểm tra trạng thái trước khi sửa

- Đọc lại đặc tả gốc và audit `2026-11-04-23-rag-resume-audit-and-progress.md`.
- Xác nhận đúng nhánh và working tree có nhiều thay đổi tracked/untracked của Zeno/Gauss và các lượt trước; không xóa, reset hoặc làm lại các module đã có.
- Audit trước đó vẫn đúng: pytest chỉ chứng minh contract code, không chứng minh chất lượng câu trả lời production; 34 nhãn người vẫn pending và kết quả AI không được đổi tên thành human review.

## 2. Implementation đã hoàn thành trong lượt này

### 2.1. Rollback reindex sau publish

- Thêm `DocumentIndexSnapshot`, lưu trạng thái document, toàn bộ chunk/embedding/metadata và mapping catalog theo version, tenant và document.
- Trước khi thay index đã publish, ingestion tạo snapshot trong cùng transaction. Publish lỗi thì snapshot cũng rollback.
- `restore_index_snapshot` khóa document, kiểm tra tenant/document/snapshot, kiểm tra mapping catalog còn thuộc đúng tenant, điều chỉnh quota, chụp checkpoint `pre_rollback`, thay index atomically rồi mới commit.
- Giới hạn giữ mặc định 5 snapshot/document qua `RAG_INDEX_SNAPSHOT_RETENTION`.
- Migration tenant `20261104_0017` đã được tạo nhưng **không chạy**. Alembic static head được xác nhận là một head: `20261104_0017`.

Giới hạn: chưa đo dung lượng snapshot embedding, thời gian restore hoặc khóa đồng thời trên PostgreSQL staging. Chưa có phê duyệt vận hành cho API/CLI restore; service hiện là primitive an toàn để tích hợp sau.

### 2.2. Benchmark A/B ghép cặp và human review

- Giữ comparator fail-closed hiện hữu.
- Thêm `prepare_rag_human_review.py`: chỉ tạo bảng review khi hai arm có cùng case key, shop, snapshot/hash câu hỏi, model và sampling config; cột quyết định/reviewer để trống; từ chối ghi đè.
- Không sinh nhãn người, không chuyển nhãn AI thành nhãn người và không tạo quality PASS.

### 2.3. Vision image-to-catalog offline

- Mọi nhánh image-to-catalog hiện cùng chịu feature flag `RAG_IMAGE_CATALOG_MATCH_ENABLED`; mặc định OFF.
- Fast path đọc SKU trong ảnh chỉ kết thúc khi thật sự đọc được SKU hợp lệ. Ảnh không đọc được mã hoặc provider lỗi có thể đi tiếp sang matcher tenant-catalog có giới hạn, thay vì chặn toàn bộ lượt.
- Thêm seam xử lý tối đa hai ảnh, trạng thái `matched/ambiguous/unmatched/provider_error`.
- Test offline bao phủ tenant isolation, SKU/variant, nhiều ảnh, ảnh mờ, provider failure và flag mặc định OFF. Không gọi provider thật.

### 2.4. Naturalness và tool routing

- Giữ planner/Graph và SQL shortcut hiện hữu; không thêm LLM call.
- Formatter chỉ bỏ citation/Markdown trình bày, chuẩn hóa khoảng trắng/dấu câu và không paraphrase. Regression giữ nguyên tên riêng, số tiền, số lượng và mã.
- Router có regression buộc câu hỏi giá/tồn kho đi qua live catalog, không coi tài liệu RAG cũ là nguồn duy nhất.

### 2.5. Benchmark multimodal 15 nhóm

- Thêm manifest đủ 15 nhóm theo đặc tả, kèm hành vi mong đợi và điều cấm.
- Khóa 11 ngưỡng trước khi chạy: nhận diện ảnh, catalog match, exact variant, grounding, naturalness, memory, clarification, hard error, p95, số LLM call và chi phí.
- Yêu cầu tối thiểu 5 case/nhóm. Hiện mới có 1 template/nhóm, không có snapshot/runtime evidence/reviewer người nên validator trả `NOT_READY`, `quality_pass=null`.

## 3. File thêm hoặc sửa trực tiếp trong lượt này

- `backend/app/models/document.py`
- `backend/app/models/__init__.py`
- `backend/app/core/config.py`
- `backend/app/services/document_index_snapshot_service.py`
- `backend/app/services/ingestion_service.py`
- `backend/alembic_tenant/versions/20261104_0017_document_index_snapshots.py`
- `backend/app/services/auto_reply_service.py`
- `backend/app/rag/answer_guard.py`
- `backend/scripts/prepare_rag_human_review.py`
- `backend/scripts/validate_multimodal_benchmark.py`
- `backend/test_data/rag_multimodal_benchmark_v1.json`
- Các regression test tương ứng trong `backend/tests/`.

Các file khác trong `git status` là working tree dùng chung từ trước; báo cáo này không nhận là thay đổi riêng của lượt hiện tại.

## 4. Test tự chạy

| Phạm vi | Kết quả |
| --- | --- |
| Safe reindex + recovery contract | 39 passed |
| Paired comparator + human-review preparation | 8 passed |
| Vision offline contract và adapter logic giả lập | 31 passed |
| Multimodal/formatter/router/vision focused | 108 passed |
| Regression rộng Graph/RAG/catalog/reindex/memory/consent/vision/benchmark | 574 passed trong 193,59 giây |
| Formatter/routing/Graph sau thay đổi cuối | 111 passed |
| `compileall backend/app backend/scripts` | PASS |
| `git diff --check` | PASS; chỉ có cảnh báo LF/CRLF của Git trên Windows |
| Alembic tenant static heads qua `.migrationdeps` | một head `20261104_0017` |

Không có migration/reindex thật, DB production, provider staging/live, webhook-to-delivery hay browser/channel test trong lượt này.

## 5. Acceptance evidence

- **Implementation:** có code và regression tests cho năm ưu tiên được giao.
- **Test coverage:** pass trên fixture/local contract nêu ở trên.
- **Quality acceptance:** **NOT READY / NOT TESTED**, không phải PASS. Validator multimodal báo 15/15 case thiếu runtime evidence và 15/15 thiếu human review; mỗi nhóm cũng chưa đạt tối thiểu 5 case.
- **Production acceptance:** chưa có. Cần staging credential/media adapter, catalog snapshot đã phê duyệt, reviewer người, paired run cùng model/prompt/config, p50/p95/calls/token/cost và rehearsal rollback PostgreSQL.

## 6. Blocker và điều kiện nghiệm thu production

1. DBA/release owner chạy migration trên staging và đo storage/lock/restore; thực hiện rehearsal publish xấu -> rollback -> kiểm tra quota/mapping/embedding. Không thử trực tiếp production.
2. Thu thập ít nhất 5 case thật cho mỗi trong 15 nhóm, khóa ảnh bằng SHA-256 và catalog snapshot; reviewer người độc lập chấm các trường đã khai báo.
3. Chạy A/B paired trên cùng question, snapshot, prompt, model và sampling config. Hard error phải bằng 0; không đạt thì không bật.
4. Chạy media adapter theo từng kênh ở staging và kiểm tra duplicate send/provider failure. Feature vision vẫn OFF cho tới khi gate đạt.
5. Đo naturalness và tool choice bằng review người; unit test formatter không thay dữ kiện không thay thế đánh giá câu văn thực tế.
6. Sau khi đủ evidence mới đề xuất canary từng shop, giám sát và rollback; chưa có quyền bật trong lượt này.

## 7. Independent final review sau khi tiếp tục phiên bị ngắt

Gauss đã được giao review độc lập trước khi phiên bị giới hạn, nhưng agent kết thúc ở trạng thái lỗi do hết giới hạn và không trả về nhận xét có thể kiểm chứng. Vì vậy lượt này thực hiện lại review độc lập trực tiếp trên trạng thái working tree hiện tại, không coi việc Gauss đã được giao là bằng chứng review.

### 7.1. Hai lỗi P1 đã phát hiện và xử lý

1. **Quota sau rollback không cùng transaction với index ở single-DB.** Khi snapshot đích có ít chunk hơn, `release_quota` từng chạy sau `db.commit()`. Thay đổi usage vì vậy có thể chỉ tồn tại trong session và không được commit. Đã chuyển release local vào trước commit để index và quota cùng atomically publish.
2. **Lỗi đối soát quota cross-DB sau publish gây false failure.** Index đã commit nhưng lỗi khi release quota platform từng đi vào nhánh rollback rồi ném lỗi, khiến caller có thể hiểu sai rằng restore thất bại và thử lại. Đã tách trạng thái `published`: lỗi bookkeeping sau publish được log, restore vẫn trả thành công; quota bảo thủ còn lệch phải được recovery/reconciliation xử lý riêng.
3. **Comparator chưa chứng minh reviewer là người.** Chỉ cần điền `reviewed_by` là nhãn AI có thể lọt qua. File review giờ có `reviewer_type`; comparator bắt buộc `reviewer_type=human`, `reviewed_by` và `reviewed_at` đều có giá trị. Nhãn AI hoặc nhãn không có attestation bị từ chối fail-closed.

### 7.2. Regression bổ sung

- Xác minh release quota local xảy ra trước commit restore.
- Xác minh lỗi quota platform sau publish không biến restore thành thất bại giả.
- Xác minh rollback lặp `2 chunks -> 1 -> 2 -> 1` giữ đúng nội dung và quota mỗi lượt.
- Xác minh comparator từ chối reviewer AI, reviewer không attested và thiếu thời điểm duyệt.
- Xác minh bảng review mới vẫn để trống toàn bộ trường quyết định và provenance người duyệt.

### 7.3. Test thực chạy trong lượt final review

| Phạm vi | Kết quả |
| --- | --- |
| Rollback/quota + human-review + vision cache/offline + multimodal contract | **58 passed** trong 154,86 giây |
| Rollback/quota lặp + comparator + review preparation sau thay đổi cuối | **50 passed** trong 156,98 giây |
| Python compile các file service/script/test đã sửa | PASS |
| `git diff --check` | PASS; chỉ cảnh báo LF/CRLF đã có trên Windows |

Suite 574 test là kết quả đã chạy trước final review. Vì thay đổi cuối chỉ chạm service rollback, benchmark scripts và test tương ứng, lượt này chạy lại các suite chịu ảnh hưởng thay vì nhận 574 test cũ là bằng chứng cho code mới.

### 7.4. Review các vùng ưu tiên không phát hiện blocking mới

- Tenant/document/snapshot đều được scope bằng `business_id` và `document_id`; mapping catalog được kiểm tra lại thuộc tenant trước restore.
- Cache vision khóa theo tenant, model, loại phân tích và SHA-256 ảnh; giá/tồn kho không được cache. Feature flag vision vẫn mặc định `False`; provider failure có kết quả giới hạn và test offline.
- Formatter chỉ bỏ citation/Markdown trình bày, không paraphrase; regression giữ nguyên tên, giá, tồn kho và SKU.
- Rollback nhiều lần đã có regression local. Tuy nhiên lock/concurrency, thời gian restore và quota bridge thật vẫn chưa được rehearsal trên PostgreSQL staging.

### 7.5. Trạng thái bàn giao

- **IMPLEMENTED:** versioned snapshot/restore, A/B review preparation, vision contract mặc định OFF, formatter/routing, multimodal manifest/validator; cộng ba sửa lỗi P1 nêu trên.
- **TESTED:** unit/integration local theo các suite được liệt kê. Không có provider thật, migration thật, reindex thật hoặc channel delivery.
- **REVIEWED:** diff hiện tại được review lại trực tiếp theo atomicity, tenant scope, mapping, quota, rollback lặp, vision isolation/failure, human-label gate và formatter facts. Gauss không tạo được review artifact do agent lỗi giới hạn.
- **ACCEPTANCE VERIFIED:** **CHƯA**. Chưa có human-reviewed paired benchmark hợp lệ, staging rollback rehearsal, PostgreSQL concurrency/storage measurement hoặc multimodal runtime evidence. Không được tuyên bố quality PASS hay bật production từ kết quả này.
