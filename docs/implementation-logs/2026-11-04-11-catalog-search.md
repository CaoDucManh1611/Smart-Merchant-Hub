# Mục 2 — Catalog Search có điều kiện

Ngày: 2026-11-04. Nhánh có sẵn `codex/rag-rfm-all-updates-20261104`; HEAD lúc kiểm tra `92ae7e34c532d3d5b331e3c7343dcd9a20375f61`.

## Phạm vi và bảo toàn working tree

- Không tìm thấy `AGENTS.md` trong repo, các thư mục cha, hoặc cây backend/docs đã kiểm kê.
- Chỉ sửa `backend/app/services/business_request.py`; tạo `backend/app/services/catalog_search.py`, `backend/tests/test_catalog_search_contract.py` và log này.
- Repo có nhiều dirty changes từ đầu và được cập nhật đồng thời. Không checkout/reset/stash, không sửa `conversation_graph.py`, không commit/push, không gửi Telegram. Những thay đổi ngoài bốn file trên không thuộc patch này.
- Đã đọc kế hoạch log 08, phản biện log 09, resolver, hard filters, model/schema/profile/module gating và các luồng workflow liên quan.

## Phân tích caller và lỗi gốc

Kiểm kê `current_offerings` trong app/tests trước sửa:

| Caller | Hành vi cũ | Xử lý |
| --- | --- | --- |
| `business_request.advance_business_request`, trước LLM | Lấy 100 Product + 100 AppointmentService đầu theo ID cho prompt | Search theo câu hiện tại, tối đa 12; bổ sung pending ref đọc mới trong cùng trần 12 |
| Cùng workflow, chọn ref và đọc lại sau `with_for_update` | Xác thực ref bằng membership trong tập 100/100 | Exact lookup tenant/active độc lập cửa sổ search, cả trước và sau khóa row |
| `conversation_graph`, nhánh catalog | Đưa tập 100/100 vào evidence | Giữ wrapper tương thích để main tích hợp; không sửa graph |
| Tests business request / graph | Import/patch API cũ | Giữ vị trí tham số `profile` thứ ba và cấu trúc list/dictionary |

Graph working tree quan sát cuối lượt đã gọi wrapper với `query=typed_catalog_query, kind=typed_catalog_kind, limit=12`; đây là thay đổi của main. Main cũng thông báo nhánh recommendations đọc exact từng ranked ref và common serving tests 125 passed; không nhận các phần đó là thay đổi hoặc kết quả test của patch này.

## Contract bàn giao

```python
from app.services.catalog_search import search_current_offerings, get_current_offering
# Cũng được re-export qua app.services.business_request.

search_current_offerings(
    db, business_id, query, limit=12, *, profile=None,
    hard_filters=None, kind=None, budget=None, offset=0,
) -> list[dict]

get_current_offering(db, business_id, ref, profile=None) -> dict | None

# Wrapper giữ các lời gọi cũ với profile ở vị trí thứ ba:
current_offerings(db, business_id, profile=None, query="", limit=12, **filters)
```

- `limit`: integer 1..100, dùng chung hai nguồn; `offset`: integer >=0. Đây là giới hạn trang SAU lọc, không phải cắt 100 ứng viên đầu trước tìm kiếm. Mặc định API cũ nay trả tối đa 12 mục; không được hiểu là toàn bộ catalog.
- `kind`: `goods|service|rental`, đọc từ `metadata.offering_type`, fallback về business profile như trước. AppointmentService luôn là service. Không suy loại từ tên ngành/sản phẩm.
- `hard_filters`: tái dùng `validate_hard_filters`/`extract_query_hard_filters`, gồm `object_type`, `sku`, `required_attributes`; không nhận business_id từ filter/model. `object_type=product` chỉ nguồn Product (có thể chứa goods/service/rental), `service` chỉ AppointmentService, `rental` chỉ Product có kind rental. Muốn tất cả loại dịch vụ từ hai nguồn, dùng `kind="service"`.
- SKU là exact, không prefix; tối đa 10 mã theo validator hiện có. Mã có nhãn trong query được dùng làm exact constraint. SQL ưu tiên exact SKU trước tên/curated alias, rồi mới lexical candidates và ID ổn định. Resolver chỉ chạy trên trang đã chọn, không load whole catalog.
- Attributes dùng alias key/value hiện có, so khớp scalar/array trong JSON bằng SQL EXISTS; duration của AppointmentService lấy từ cột duration_minutes. Nested attributes ưu tiên hơn metadata legacy nếu có giá trị. Không dùng tên/mô tả thay bằng chứng thuộc tính/fitment; thiếu dữ liệu không đạt hard filter.
- Caller filter tường minh ưu tiên hơn phần query tự trích. Budget dùng parser `stated_budget` hiện có nếu caller không truyền; ceiling inclusive theo giá đơn vị, Decimal finite >=0; không tự diễn giải ngân sách tổng giỏ.
- Mọi nhánh nguồn có business_id và active predicate trước LIMIT/UNION. Chỉ hydrate ID của trang đã chọn, đọc mới price/stock bằng populate_existing. Giá/kho/status lấy bảng nguồn hiện hành, không đọc bản mirror recommendation làm sự thật.
- Exact ref chỉ nhận `product:N|service:N`, positive int32 dạng chuẩn; sai format, khác tenant, inactive, thiếu row trả None. AppointmentService còn cần module appointments bật. Không bị ảnh hưởng budget/search/page; hàng active hết tồn vẫn trả snapshot với available=0 để workflow tự chặn.
- Cấu trúc kết quả giữ `ref,name,kind,price,billing_unit,available,availability_basis,description`; Product có `sku`, AppointmentService có `duration_minutes`. Giá là string; description tối đa 1000 ký tự.

## Bảo toàn workflow

Giữ khóa Conversation, khóa resource tenant scoped `with_for_update`, quota/idempotency keys, chứng cứ CURRENT text, contact encryption, validation fields, reset khi đổi offering, review/explicit confirmation, kiểm giá hiện hành, kiểm tồn và nhánh lịch hẹn xung đột. Exact lookup tự nó là read helper, không cấp khóa hoặc tạo order; workflow vẫn đọc lại sau khi khóa. Không đổi phần ghi order/payment/notification.

## Kiểm thử thực tế

### Harness mặc định — kết quả chính để review

Không đặt `RUN_POSTGRES_TESTS` ở các lượt dưới: output xác nhận `<unset; conftest default=1>`. `conftest.py` remap URL `sqlite://` của fixture sang PostgreSQL disposable schemas. Hook pytest đọc trực tiếp `catalog` session `get_bind().dialect.name`: **postgresql**. Vì vậy các ca fixture catalog bên dưới là runtime PostgreSQL, không phải SQLite/in-memory.

| Lượt chạy | Kết quả |
| --- | --- |
| `tests/test_catalog_search_contract.py` | **51 passed in 18.93s**; actual engine **postgresql** |
| `tests/test_conversation_graph.py` | **28 passed in 34.13s** với harness mặc định; các ca graph dùng mock theo test gốc |
| `test_business_request.py::test_three_business_types_collect_review_then_submit` (3 parametrizations) và `::test_price_update_requires_new_approval_and_uses_live_price` | **4 passed in 35.99s**, harness PostgreSQL mặc định |

Lệnh catalog thực tế được chạy bằng `pytest.main` với các args sau và plugin EngineAudit chỉ in dialect của fixture (không đổi cấu hình DB):

```text
tests/test_catalog_search_contract.py -q -p no:cacheprovider
--basetemp=.pytest_tmp/catalog-search-default-20261104
```

Fixture catalog chỉ dựng schema disposable một lần/module; từng test có connection transaction riêng, Session `join_transaction_mode="create_savepoint"`; commit của workflow chỉ release savepoint, transaction ngoài rollback cả seed/giao dịch. Không ghi dữ liệu CRM đang phục vụ hoặc gọi provider thật.

Tổng ba lượt mặc định: **83 passed** (51 catalog + 28 graph + 4 workflow). Python AST parse ba file scoped PASS; `git diff --check` cho file tracked business_request PASS. Không nhận kết quả 125 common tests của main là kết quả tự chạy của patch này.

51 ca phủ: hơn 100 goods và appointment services; SKU/tên/alias trong câu tự nhiên; SKU thắng tên trùng mã; rental/Product-service; tenant, inactive, module gating, budget trước LIMIT, attribute scalar/array/boolean, nested precedence, không đoán fitment từ tên, shared limit/pagination, malformed/foreign/exact refs, refresh giá/tồn, pending choice ngoài trang search, bốn workflow loại offering đến submitted, active thay đổi sau lookup đầu và trước đọc lại sau khóa. Có compile kiểm tra SQL PostgreSQL native JSON và bound parameters; các compile-only checks được phân biệt với runtime PostgreSQL của các contract tests khác.

### Lượt phụ trước khi người dùng yêu cầu dùng harness mặc định

Đã từng đặt `RUN_POSTGRES_TESTS=0`: các lượt đó thực sự chạy SQLite và chỉ là bằng chứng phụ. Snapshot trước bổ sung assertion duration có nhóm catalog/business-request/workflow-regressions/resolver **92 passed in 16.45s**. Lượt sau thêm assertion duration dùng prefix không được parser chung nhận có **91 passed, 1 failed**; đã sửa ca sang nhãn được parser hiện có hỗ trợ và kiểm tra lại bằng PostgreSQL mặc định ở trên. Một lượt default trước tối ưu fixture bị dừng khi chưa hoàn tất, không tính PASS.

Lượt mở rộng SQLite trước đó: **147 passed, 2 failed** (snapshot trước thêm ca ưu tiên SKU). Hai lỗi nằm ngoài scope:

- `test_rental_enquiry_collects_contact_and_notifies_without_creating_order`: dùng ngày 01/11/2026 đã qua so với runtime 04/11/2026. Tái hiện khi nạp `business_request` nguyên bản HEAD vào bộ nhớ: 1 failed/1 passed cho hai ca kiểm tra đơn lẻ.
- `CustomerCollectionFlowTests.test_quantity_purchase_followup_uses_last_product_and_waits_for_confirmation`: pass khi chạy riêng, fail khi chạy cả file. Nạp `business_request` HEAD trong bộ nhớ và chạy nguyên file vẫn **49 passed, 1 failed**. Chưa kết luận sâu nguyên nhân phụ thuộc thứ tự/data; không sửa file ngoài scope.

Đối chứng HEAD dùng `git show` rồi `exec` trong module của subprocess test; không checkout/ghi đè file source và không reset dirty changes. Không coi hai lỗi SQLite phụ trên là kết quả fail của lượt PostgreSQL targeted, cũng không tuyên bố full regression suite đã sạch.

## Gates và pitfalls còn lại

- Đã đạt targeted contract trên PostgreSQL disposable; chưa đo trên catalog production, chưa chạy live chat/provider, chưa benchmark latency/query plans hoặc stress concurrent PostgreSQL locking. Không tuyên bố rollout/production gate PASS.
- SQL lexical dùng lower/trim và query token gốc + resolver normalization; không yêu cầu extension unaccent. Tìm không dấu/Unicode/collation có thể chưa có recall đầy đủ; dùng SKU/curated alias/structured filters khi cần exact. Đây là candidate search, không phải xác minh tương thích.
- Parser thuộc tính chỉ hỗ trợ nhãn rõ và alias hiện có. Caller nên truyền hard_filters đã xác thực cho câu xe/năm/thuộc tính phức tạp; không suy chứng cứ fitment từ lexical name match. SQL attributes chỉ đọc metadata nguồn, không tự backfill từ mô tả.
- Budget theo món và giá rental theo billing unit; ngân sách tổng/số lượng hoặc lịch thuê theo ngày cần bước nghiệp vụ tương ứng. Tồn rental không chứng minh rảnh ngày; service vẫn cần staff-reviewed schedule.
- Trang trả về có thể ngắn khi trạng thái đổi giữa select IDs và hydrate. Search không phải booking snapshot có khóa; workflow exact+row-lock+review chịu trách nhiệm giao dịch.
- Không nâng LIMIT để giả giải quyết recall, không load toàn catalog vào prompt. Danh sách toàn bộ phải đi qua offset/limit và UI/handoff phù hợp của main.
