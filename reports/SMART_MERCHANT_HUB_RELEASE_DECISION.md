# Smart Merchant Hub — Final Stabilization & Release Decision

**Ngày:** 2026-11-06 (Asia/Bangkok)  
**Branch / HEAD:** `codex/rag-rfm-all-updates-20261104` / `92ae7e34c532d3d5b331e3c7343dcd9a20375f61`  
**Phạm vi:** Case 002, Graph → Recommendation → RFM → final answer với dữ liệu synthetic, provider reliability offline và quyết định phát hành. Không commit, push, deploy, migration, provider call, hay truy cập production.

## Kết quả

```text
SALES_RECOMMENDATION=CASE_002_FIXED_AND_OFFLINE_SYNTHETICALLY_VERIFIED
RAG_RFM_INTEGRATION=GRAPH_TO_RANKER_TO_FINAL_ANSWER_OFFLINE_VERIFIED; NO_LIVE_QUALITY_OR_RANK_SWAP_CLAIM
CONSENT_RACE_P2=OPEN
POSTGRESQL_VERIFICATION=NOT_VERIFIED
BACKEND_TESTS=2280 passed, 6 skipped, 37 subtests; exit 0; final conversation-context test 11 passed
SAFE_FOR_SYNTHETIC_DEMO=YES_OFFLINE_SYNTHETIC_ONLY
PRODUCTION_READY=NO
BLOCKERS=Consent revocation concurrency has not been tested on disposable PostgreSQL; real-provider answer quality and production runtime remain unverified.
```

## Case 002 — nguyên nhân và sửa lỗi

**Tái hiện trước sửa:** pipeline đánh giá bật `PRAGMA query_only=ON`. `recommendation_evidence()` gọi `serve_recommendations()` theo mặc định có ghi `RecommendationRequest`; SQLite từ chối câu lệnh `INSERT`. Graph bắt lỗi SQLAlchemy, bỏ kết quả xếp hạng. Catalog sau đó chỉ được truy vấn theo ID sản phẩm đã xếp hạng, nên nhận tập rỗng và cuối cùng trả câu chuyển nhân viên/không xác minh thay vì sản phẩm trong ngân sách.

**Sửa:** `recommendation_evidence()` phát hiện SQLite query-only và gọi cùng ranker với `persist=False`; trong chế độ này không ghi request hay flush trace. SQLite ghi được và database dialect khác giữ nguyên hành vi persist hiện có. Nếu không xác định được trạng thái query-only của SQLite, đường này chọn không persist thay vì thử ghi. Không thêm nhánh hardcode cho Alpha hoặc cho câu 002.

Regression dùng case `answer-002-budget` và fixture catalog synthetic: Alpha 180.000đ, tồn 3; Beta 220.000đ, tồn 9. Trước sửa test thất bại vì recommendation write bị từ chối và bot handoff. Sau sửa, Graph trả Alpha cùng giá hiện hành; không trả Beta, không chuyển sang trả lời về tương thích xe, không ghi recommendation request, và `query_only` vẫn bật.

## Graph + Recommendation + RFM

Regression chạy cùng câu hỏi ngân sách qua Graph, recommendation service, RFM ranker và câu trả lời catalog cuối, với năm persona:

| Persona synthetic | Kết quả consent/history |
| --- | --- |
| Khách mới | Không có lịch sử, không có RFM snapshot hoặc tín hiệu cá nhân hóa; dùng baseline. |
| Mua thường xuyên, đã đồng ý | Ranker nhận snapshot frequency 4, monetary 200.000 và tín hiệu RFM. |
| Giá trị mua cao, đã đồng ý | Ranker nhận snapshot frequency 2, monetary 600.000 và tín hiệu RFM. |
| Có lịch sử nhưng chưa đồng ý | Customer ID bị loại khỏi request cá nhân hóa; không snapshot, tín hiệu hay query lịch sử. |
| Đã rút consent, có lịch sử | Consent mới nhất là revoked; không snapshot, tín hiệu hay query lịch sử. |

Cả năm luồng chỉ đưa ra sản phẩm trong ngân sách, không đưa sản phẩm 250.000đ hoặc sản phẩm của tenant khác, và không phát biểu xác suất mua. Planner và retrieval được mock offline; không gọi LLM/provider. Đây là bằng chứng tích hợp của đường code offline, **không** chứng minh RFM tăng chuyển đổi, làm đổi thứ hạng có ích, hoặc cải thiện chất lượng tư vấn ngoài dữ liệu synthetic. Không có tuyên bố LightFM đã được train hoặc được chứng minh hiệu quả.

## Consent race và PostgreSQL

`CONSENT_RACE_P2` vẫn **OPEN**. Không có disposable PostgreSQL instance được chỉ định/cho phép cho thử nghiệm hai session; không kết nối bất kỳ database nào để suy ra khả năng sẵn có. SQLite regression không được tính là kiểm chứng locking, transaction isolation, connection pooling hoặc race giữa revoke consent và memory/recommendation read.

## Provider reliability — offline

Các test mock/offline trong regression bao phủ HTTP 400 structured-output failure (không xoay key), HTTP 429, `Retry-After` dạng số và HTTP-date, cooldown/key-pool, circuit breaker half-open single-flight, safe fallback, giới hạn attempt/call và dừng batch sau 429. Các test liên quan đều pass. Không gửi request tới Groq/Gemini hoặc provider khác; không đổi key/model để né quota.

## Regression và an toàn

- Focused Graph/RAG/RFM/consent/tenant/provider suite: **242 passed, 6 subtests passed**, 1 warning.
- Full backend offline: **2.280 passed, 6 skipped, 37 subtests passed**, 40 deprecation warnings, exit 0, 130.09 giây. Chạy với `RUN_POSTGRES_TESTS=0` và provider API key variables rỗng.
- Sau full suite, bổ sung assertion kiểm tra rõ câu trả lời không nêu xác suất mua; chạy lại toàn bộ `tests/test_conversation_context.py`: **11 passed**.
- `git diff --check`: exit 0. Git chỉ in cảnh báo chuyển đổi LF/CRLF đã có trong working tree.
- Effective setting được đọc offline: `SALES_JOURNEY_ENGINE_ENABLED=False`.
- `backend/test.db` không có thay đổi trong Git status; không được đưa vào hay dùng làm fixture.
- Không gọi provider, database production, webhook/kênh khách hàng, giao dịch, thanh toán, migration hay deployment.
- Working tree ban đầu có 174 status entries; được giữ nguyên. Báo cáo này là file mới duy nhất được tạo cho bàn giao; không commit/push.

## Tệp liên quan trong lượt này

- `backend/app/services/conversation_context.py` — chọn chế độ persist an toàn cho SQLite query-only trong Graph recommendation.
- `backend/tests/test_conversation_context.py` — regression Case 002 và năm persona RFM/consent/tenant qua Graph.
- `reports/SMART_MERCHANT_HUB_RELEASE_DECISION.md` — quyết định bàn giao này.

## Quyết định phát hành

Case 002 đã được sửa và kiểm chứng trên synthetic offline. Luồng Graph/RFM được tích hợp và có regression cho cả consented lẫn non-consented persona. Chỉ có thể demo trong môi trường synthetic/offline đã kiểm soát. **Chưa đủ điều kiện production**: consent race P2 chưa được kiểm chứng bằng PostgreSQL thực, PostgreSQL runtime chưa xác minh, và chất lượng câu trả lời provider/live chưa được đo hợp lệ.
