# Release readiness

**NO-GO cho production tại thời điểm chốt lượt QA này.** Quyết định dựa trên độ phủ nghiệm thu và blocker còn lại, không khẳng định có exploit mới chỉ từ thiếu bằng chứng.

|Gate|Kết quả|
|---|---|
|Source integrity|1213 file đã hash; 0 mismatch|
|Backend|Sau bản sửa QA-RAG-004: 2.294 passed, 0 failed, 3 skipped, 37 subtests passed; full offline suite PASS. Vision flag đặt false riêng cho process test.|
|Frontend|327 pass; test exit 0, build exit 0; build có JS chunk 1,152.53 kB (>500 kB warning)|
|Authentication probe|10/10 request bị chặn theo 401/403|
|PostgreSQL targeted|{"tests": 16, "failures": 0, "errors": 0, "skipped": 0, "passed": 16}|
|Runtime flags|Container env: `RAG_IMAGE_CATALOG_MATCH_ENABLED=true`; `SALES_JOURNEY_ENGINE_ENABLED` unset, code default false. Vision behavior itself NOT VERIFIED.|
|Browser UI|PARTIAL visual smoke: Codex browser desktop 1342×831 và mobile 390×844, không tràn ngang; mobile menu thu gọn, chat/input hiển thị. Không thao tác dữ liệu. E2E chức năng, console/network và viewport reset NOT VERIFIED (browser timeout).|
|RAG answer mới qua provider|NOT RUN; regression này chỉ kiểm tra routing/auto-reply offline|
|Consent concurrency, role ACL|NOT VERIFIED/OPEN|
|Backup/rollback drill|Có runbook; diễn tập mới NOT RUN|
|Load/latency business API|NOT RUN|

Điều kiện nghiệm thu còn cần là browser E2E các workflow cốt lõi bằng tenant/role thử, kiểm race consent PostgreSQL, role privileges, diễn tập restore và điều kiện TLS/monitoring của staging. Không dùng toàn bộ test xanh hay visual smoke làm căn cứ duy nhất cho GO. QA-RAG-004 hiện chỉ được xác nhận sửa ở mức offline; production vẫn NO-GO cho tới khi các gate còn lại có bằng chứng.

## Bàn giao

SYSTEM_TEST_PLAN.md, TEST_CASES.md, TEST_EXECUTION_REPORT.md, BUG_REPORT.md, SECURITY_AUDIT.md, PERFORMANCE_REPORT.md và RELEASE_READINESS.md. FEATURE_INVENTORY.md bổ sung tất cả router. Evidence có raw logs, JUnit, inventory API, scripts tái chạy và manifest. Trong lượt sửa QA-RAG-004, không commit/push/deploy.
