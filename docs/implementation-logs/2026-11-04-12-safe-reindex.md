# Mục 3 — Reindex an toàn

Ngày 2026-11-04. Repo `smart-merchant-hub`; nhánh `codex/rag-rfm-all-updates-20261104`, HEAD lúc bắt đầu `92ae7e34c532d3d5b331e3c7343dcd9a20375f61`.

## Phạm vi và căn cứ

Đã tìm `AGENTS.md` trong repo và các thư mục cha: không có. Đọc log 08/09, toàn bộ ingestion service, job service, document API và các callers trong knowledge seed/CRM worker; đọc tests ingestion fallback, RAG operations, semantic chunking, catalog và hợp đồng quota/mapping liên quan trước khi sửa. Repo có dirty work từ đầu và có thay đổi song song ngoài phạm vi trong lúc thực hiện; không reset/checkout/ghi đè chúng.

Chỉ thay đổi các file sau trong phần triển khai này:

- `backend/app/services/ingestion_service.py`
- `backend/app/services/rag_job_service.py`
- `backend/app/api/documents.py`
- Mới: `backend/scripts/audit_safe_reindex.py`
- Mới: `backend/tests/test_safe_reindex.py`
- Log này.

Không sửa `product_catalog_service.py`, Graph hoặc `main.py`. API bắt buộc phải sửa vì cả reindex và retry trước đây đều đưa tài liệu ready về pending, khiến retrieval loại index cũ trước khi có bản thay thế.

## Hành vi đã triển khai

1. **Giữ current price/stock/status.** `ingest_document(..., reindex_only=True)` bỏ qua `sync_catalog_products`. Service tự nhận diện reindex khi đã có chunk cũ để bảo vệ cả direct caller; initial ingest chưa có index vẫn sync catalog như cũ. Explicit reindex chưa có chunk cũng không nhập catalog. Worker truyền mode từ loại run/payload; retry giữ mode qua nhiều lần retry. Chỉ mirror recommendation catalog từ canonical Product hiện hành, khóa Product theo thứ tự ID trong transaction publish; không lấy giá/kho/status từ source cũ. `reserved_quantity` cũng không bị thay đổi.

2. **Quota preserve ready.** API chỉ xếp run/job cho tài liệu đang ready, giữ cả `Document.status` và `embedding_status` cũ. Service xây chunks/vectors trong bộ nhớ, giữ index cũ qua các progress commits. Advisory chunk check vẫn xảy ra trước embedding; authoritative reservation delta dựa trên số chunk rows thực tế xảy ra trước delete/insert/publish. Worker không còn reserve quota sau commit rồi xóa index khi reject.

3. **Rollback khi lỗi.** Delete/insert chunks, thay mappings và cập nhật trạng thái active nằm trong một tenant transaction, không có callback commit ở giữa. Load/empty/embedding/vector-count/mapping/store/commit error hoặc chunk/AI quota reject giữ nguyên chunks, vectors, mappings, chunk_count, processed_at và trạng thái phục vụ cũ nếu trước đó ready. Không downgrade index ready thành lexical-only do embedding error; lexical fallback của initial ingest vẫn giữ nguyên. Service trả kết quả attempt riêng; worker ghi run failed dù tài liệu vẫn ready. Lỗi progress sau publish không refund quota hoặc chuyển index thành error.

4. **Quota qua hai DB.** Tái dùng quota service hiện có. Legacy quota cùng DB rollback cùng index. Với tenant schema, quota bridge commit ở control-plane trước publish; nếu tenant publish lỗi thì release phần delta đã reserve. Chỉ release phần quota dư do shrink sau khi tenant publish thành công đối với bridge. Không release quota AI cumulative.

5. **Mapping exact SKU.** Tái dùng `sync_product_catalog_entry`, chỉ match SKU nguyên token; không link `A-001` vào `A-001-XL`. Giữ các mappings còn hợp lệ của tài liệu khác trong cùng tenant khi helper replace links. Xóa links của chunks cũ cùng transaction; rollback phục hồi chúng. Không tạo/link canonical product của tenant khác.

6. **Source disabled/index status.** API reindex/retry và service từ chối `disabled`/`superseded`; không tự bật nguồn đã tắt. API vẫn giữ dependency tenant/write, kiểm tra retained source, active run/job và khóa row để chặn queue trùng. Worker kiểm tra đúng bộ tenant/run/document và bỏ qua completed-run replay. Trong khi chạy, run/job phản ánh queued/processing còn tài liệu ready vẫn phục vụ index cũ; thất bại hiện ở run và error fields của tài liệu.

## Audit/reindex dry-run cho Main

Script chỉ có dry-run, **không có `--apply`, `--all`, enqueue hoặc gọi embedding/model**. Bắt buộc một business ID và ít nhất một document ID dương, không tự chọn toàn shop/toàn bộ tenants. Chỉ đọc active+enabled registry có schema khớp business; mọi document được chọn phải thuộc đúng tenant. PostgreSQL registry/tenant transactions dùng `SET TRANSACTION READ ONLY`.

Từ thư mục `backend`, Main gán `$businessId`/`$documentId` bằng IDs live đã chọn để review rồi chạy:

```powershell
python scripts/audit_safe_reindex.py --business-id $businessId --document-id $documentId --dry-run
```

Có thể lặp `--document-id` cho danh sách tài liệu đã chọn cùng shop. Script trả JSON theo tenant/document: source SHA-256, source/index status, có retained bytes hay không, active run/job, chunk_count khai báo/thực tế, IDs/index và SKU của chunks chứa nhiều SKU qua content/mappings, phân loại catalog/policy/guide-or-FAQ, số chunks đề xuất bằng chunker local, multi-SKU còn lại, quota delta, embedding chars/tokens ước lượng. Cost chưa biết được ghi null. Không print source content hoặc credentials khi lỗi.

SKU audit kết hợp mã canonical của tenant, nhãn SKU tường minh và mappings; mã lạ không nhãn có thể chưa được phát hiện. Chunk nhiều SKU là ứng viên cần review, có thể là policy/comparison hợp lệ. Phân loại topic và tokens chars/4 là heuristic; chunking semantic remote khi chạy thật có thể cho số lượng khác. `eligible` chỉ phản ánh các điều kiện nguồn/job, không phải xác nhận quota, chất lượng hay quyền apply.

**Chưa audit live docs, chưa apply/reindex tài liệu thật trong lượt này.** Main có thể chạy lệnh trên với đúng IDs sau khi tích hợp; script không tạo đường ghi bỏ qua authenticated API/worker.

## Bằng chứng thực nghiệm

### Harness và lượt kiểm thử

- Các lượt ban đầu chủ động đặt `RUN_POSTGRES_TESTS=0`: engine thực sự là SQLite, không phải harness PostgreSQL mặc định. Kết quả này chỉ là kiểm tra bổ sung, không thay thế gate mặc định. Lượt đầu 62 pass/5 setup errors: fixture HTTP mới vô tình chạy startup PostgreSQL (`CREATE EXTENSION`) trên SQLite test. Đã sửa fixture dùng request TestClient không startup lifespan; không sửa main, không đụng DB live. Sau sửa 67 pass; sau mở rộng tests và bridge checks, lượt SQLite liên quan cuối có 87 pass.
- Theo yêu cầu Main, đã bỏ override `RUN_POSTGRES_TESTS` và chạy lại harness mặc định. Trong harness này `create_engine("sqlite://")` được remap sang **PostgreSQL, disposable test schemas**, nên tên URL ở fixture không phải bằng chứng SQLite/in-memory. Không chạy migration CLI hay restart services.
- Đọc metadata PostgreSQL test-only bằng `pg_stat_activity` cũng thấy các backends `crm_chatbot_test`/`crm_tenant_test` với application name `smh_pytest_*` trong lúc chạy; không in DSN/credentials. Không dùng SQLite URL literal để gán nhãn engine cho lượt default.
- Kết quả default đang được hoàn tất; phần này sẽ được cập nhật trước bàn giao.

Lệnh default (không đặt `RUN_POSTGRES_TESTS=0`; Gemini keys để rỗng và embeddings trong tests được stub):

```powershell
python -m pytest tests/test_safe_reindex.py tests/test_ingestion_embedding_fallback.py tests/test_rag_operations.py tests/test_semantic_chunking.py tests/test_product_catalog_service.py tests/test_quota_service.py tests/test_platform_quota_ledger.py tests/test_rag_tenant_isolation.py tests/test_tenant_worker_routing.py tests/test_crm_job_worker.py -q --tb=short
```

Các ca mới kiểm tra giá/kho/status/reserved quantity, recommendation projection từ current Product, giữ mappings tài liệu khác/tenant khác, lỗi load/empty/embedding/vector mismatch/mapping/commit, preflight/final quota/AI quota, delta lặp/shrink, rollback quota local và compensation control-plane riêng, retrieval lexical trong mọi progress phase, run failed/doc ready, API queue/retry/disabled/write guards, exact SKU prefix và audit không ghi/không có apply.

### Dry-run smoke, không phải dữ liệu live

Đã chạy `--help` và chạy `audit_documents` trên fixture standalone SQLite thực sự, ngoài pytest harness, với socket connect bị chặn. Fixture business 41/doc 1: 1 old chunk chứa `a-001` + `b-002`; đề xuất local 2 chunks, 0 multi-SKU còn lại, quota delta 1, 168 embedding chars, khoảng 42 tokens, cost null. SQLite `total_changes()` trước/sau audit bằng nhau. Đây là dữ liệu synthetic, không phải tenant 41 hay document 1 trong hệ thống live. Các tests audit riêng cũng chạy lại trong default PostgreSQL harness.

`compileall` cho ba source files/script/test và `git diff --check` phần source đã pass. Không suy diễn thành live/provider/production PASS.

## Giới hạn vận hành

- Tenant DB và control-plane quota là hai transactions hiện hữu, không có distributed transaction hay durable compensation ledger mới. Process hard-kill giữa external reservation và tenant commit/compensation, hoặc lỗi release quota, có thể để quota giữ dư cần đối soát. Index cũ vẫn còn khi chưa commit. Không claim crash recovery/đồng thời nhiều workers đã được chứng minh live.
- Rollback ở đây là rollback transaction trước publish; không lưu lịch sử phiên bản index sau khi publish thành công. Không migration để thêm version tables.
- Chưa kiểm tra live retrieval, latency, Recall/NDCG, provider retry thật hoặc ảnh hưởng catalog lớn. Có giữ canonical row locks nhưng chưa load-test chi phí quét/link toàn catalog của luồng cũ.
- Không commit/push, không apply reindex hàng loạt, không gọi embedding network, không restart dịch vụ và không chạy migration CLI.
