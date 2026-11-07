# Kết quả thực thi QA

HEAD `c6895046f69773ed40db83ecc053faabce911e18`. Ngày 07/11/2026. Source hash kiểm trước/sau `1213` file; số mismatch `0`. Danh sách tại source-integrity.json, loại trừ DB/.env và báo cáo.

|Bài chạy|Kết quả|Bằng chứng|
|---|---|---|
|Backend offline toàn bộ (lần tiếp tục)|2.293 passed, 1 failed, 3 skipped, 37 subtests passed; exit 1; pytest 150.37s|backend-final.log, backend-final.xml, qa-final-20261107-backend-full-result.json|
|Frontend Node (lần tiếp tục)|327 PASSED, 0 FAILED, 0 SKIPPED; exit 0|frontend-final.log, frontend-final-result.json|
|Frontend Vite build (lần tiếp tục)|Exit 0; JS chunk 1,152.53 kB, vẫn có cảnh báo chunk >500 kB|frontend-build-final.log, frontend-final-result.json|
|Probe auth trực tiếp|10/10 request thiếu/hỏng token nhận 401/403|live-readonly.json|
|OpenAPI|200, 405 operations|api-inventory.json|
|Health trực tiếp|11/11 HTTP 200; revision ghi trong JSON|live-readonly.json|
|PostgreSQL targeted|{"tests": 16, "failures": 0, "errors": 0, "skipped": 0, "passed": 16}|postgres.log, postgres.xml nếu có|
|Browser UI mới|BLOCKED; Computer Use không thấy cửa sổ ứng dụng, Chrome đang ở YouTube. Không đăng nhập hoặc thao tác UI|browser-blocker.txt; phiên QA hiện tại|
|LLM/provider mới|NOT RUN|Không gửi request provider trong lượt QA này|

JUnit hiện tại tổng hợp cả subtests: tests=2334, failures=1, errors=0, skipped=3, passed=2330 (gồm 37 subtests); pytest summary tương ứng 2293 passed, 1 failed, 3 skipped. Lần tiếp tục dùng `RAG_IMAGE_CATALOG_MATCH_ENABLED=false` trong process test nên lỗi môi trường vision không còn; phát hiện regression `test_room_catalog_with_price_bypasses_exact_product_lookup`, tái hiện riêng 1 failed/1. Xem QA-RAG-004 trong BUG_REPORT. PostgreSQL dùng 16 ca trong test_database_boundaries.py, test_authenticated_tenant_session.py và test_api_tenant_isolation.py; có kiểm search_path thực tế. Container tmpfs smh-qa-disposable-20261107 đã được stop/remove sau lần chạy trước. Chưa kiểm race consent hai session, role ACL ứng dụng hoặc full migration PostgreSQL trong lượt này.

Full backend lượt trước có 1 failed ở test_image_catalog_flag_defaults_off do backend/.env bật flag. Lần tiếp tục đặt `RAG_IMAGE_CATALOG_MATCH_ENABLED=false` trong process test: full suite không còn lỗi này, nhưng phát hiện lỗi rental listing nêu trên. Lỗi rental test cũng fail khi chạy lặp riêng. Không sửa test hay source trong lượt QA này.

## Lệnh và lần chạy lỗi ban đầu

Backend dùng `backend/.venv/Scripts/python.exe docs/qa/evidence-20261107/scripts/offline_backend.py`. Bộ chạy đặt RUN_POSTGRES_TESTS=0 và chặn mạng ngoài. Lần đầu chặn cả socketpair Windows, gây nhiều test lỗi hạ tầng; dừng ở khoảng 61%, giữ backend-initial-harness.log. Không có tổng kết của lần bị ngắt và không tính nó là lỗi ứng dụng. Chỉnh QA harness cho loopback ephemeral, chạy test_auth_api.py kiểm tra 7 PASSED, sau đó chạy lại full suite. Không thay app hoặc test hiện có.

Lệnh backend đầy đủ được ghi trong `qa-final-20261107-backend-full-result.json` (`offline_backend.py -q --tb=short --junitxml=...`, vision flag false; mạng ngoài bị chặn, SQLite fixtures cô lập). Ca rental được chạy lại riêng với cùng runner; log/JUnit tại `rental-failure-repro.log` và `.xml`. Frontend chạy `npm test -- --run` và `npm run build -- --outDir ../docs/qa/evidence-20261107/frontend-build-final`; kết quả/exit codes trong `frontend-final-result.json`. Probe bằng `python docs/qa/evidence-20261107/scripts/live_readonly.py`.

## Phạm vi còn thiếu

Mọi endpoint không có request/test tương ứng vẫn NOT RUN. UI desktop/mobile được kiểm tra trực quan một phần trong Codex browser: desktop 1342×831, mobile 390×844, không tràn ngang ở hai viewport; menu mobile thu gọn và khung chat/ô nhập còn hiển thị. Không gửi tin hay thao tác dữ liệu. Tab hiển thị hộp thư có nội dung nên không đi qua hồ sơ khách; đăng nhập, điều hướng chức năng, keyboard, back/refresh/logout và real-channel chưa nghiệm thu. Đọc console/network và xác nhận khôi phục viewport bị timeout nên các trạng thái đó là NOT VERIFIED. Không dùng HTTP 200 thay browser acceptance. Performance chỉ có health tuần tự (lần probe mới: 22 request, median health 533.56 ms). Không kiểm load, DB outage trên hệ thống đang phục vụ hoặc khôi phục backup thật. Full backend sau sửa QA-RAG-004 sạch; release vẫn NO-GO do các gate còn lại.

Container đang chạy có `RAG_IMAGE_CATALOG_MATCH_ENABLED=true`; đây là quan sát cấu hình, không phải kiểm chứng chất lượng nhận diện ảnh. `SALES_JOURNEY_ENGINE_ENABLED` không được đặt trong environment của container; code default là `False`. Các test offline đặt riêng flag ảnh thành false để ca kiểm default không bị `.env` của dev chi phối.

## Retest sau khi sửa QA-RAG-004 — 07/11/2026

- Regression trước sửa: `qa-rag-004-retest-before.log` — 1 failed, tái hiện exact lookup bị gọi cho truy vấn liệt kê phòng trọ.
- Sau sửa: `qa-rag-004-retest-after.log` — 1 passed; `qa-rag-fix-focused-20261107.log` — 85 passed.
- Full backend offline: `qa-backend-full-fixed-20261107.log` — 2.294 passed, 3 skipped, 37 subtests passed, 0 failed; 150.86 giây. JUnit: `qa-backend-full-fixed-20261107.xml`.
- Frontend: `qa-frontend-tests-fixed-20261107.log` — 327 passed; build `qa-frontend-build-fixed-20261107.log` exit 0. Vite vẫn cảnh báo JavaScript chunk 1,152.53 kB.
- `git diff --check`: PASS. Không chạy provider thật, migration, reindex hoặc gửi tin.
- UI responsive visual smoke đã thực hiện trong Codex browser như mô tả trên; không phải nghiệm thu UI E2E. Console/network chưa đọc được và reset viewport không được xác nhận do timeout.
- PostgreSQL runtime/consent race không chạy lại trong lượt này; 16 disposable PostgreSQL tests là bằng chứng của lượt QA trước, không gộp thành test mới.

## Dữ liệu quan sát trong lượt trước

Lượt trước có ảnh 3 câu chưa đạt về tính tổng, tên không tồn tại và đổi biến thể; chúng được ghi vào BUG_REPORT là lịch sử cần retest, không gộp thành lỗi vừa tái hiện. Ảnh và tài liệu nghiệm thu cũ ở Downloads/SMH_MinhChung, không chứa trong kết quả fresh tự động này.
