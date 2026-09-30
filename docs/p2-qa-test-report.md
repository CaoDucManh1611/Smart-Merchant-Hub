# P2 QA và kiểm thử nghiệp vụ

**Ngày:** 2026-09-13
**Branch:** `codex/p0-p2-release-audit`
**Môi trường:** Docker Compose hiện chạy PostgreSQL, Redis, backend, worker và Vue frontend; test API dùng fixture SQLite cô lập.

## Kết luận phát hành

**Các phần P2 đã có mã nguồn đạt kiểm thử nội bộ; toàn bộ P2 chưa thể đánh dấu hoàn tất.**

Workflow builder, workflow worker, metadata vận chuyển nội bộ, payment/refund nội bộ,
saved customer segments và registry thử nghiệm schema-per-tenant đã qua test chức năng,
tenant isolation và nghiệp vụ. Một lỗi thật ở endpoint dispatch workflow đã được sửa.

Các hạng mục sau hiện là khoảng trống triển khai, không phải test fail: saved views/bulk
actions tổng quát, đồng bộ hãng vận chuyển thật, payment gateway thật, hóa đơn điện tử,
white-label/agency multi-shop và provisioning schema/database riêng cho từng tenant.

## Bằng chứng chạy test

| Cổng kiểm tra | Kết quả |
|---|---:|
| Backend unit/API/integration/business regression | **455 passed, 0 warnings** |
| Frontend behavior regression | **106 passed** |
| Frontend production build (`vite build`) | **PASS** |
| Python compile check | **PASS** |
| Git whitespace/error check | **PASS** |
| Docker runtime | **5/5 healthy** |
| Backend `/health` | **HTTP 200** |
| Frontend `/` | **HTTP 200** |
| Runtime GET workflow/order/dispatch smoke | **HTTP 200** |

Hai warning cũ đã được xử lý: test dùng thời gian UTC aware và tích hợp Gemini đã
chuyển sang SDK `google.genai` đang được hỗ trợ.

**Baseline dữ liệu:** backend đang dùng database `crm16_restore`; truy vấn read-only
sau test xác nhận đúng `8 conversations / 713 messages`. Database mặc định
`crm_chatbot` trong cùng PostgreSQL cluster là bộ demo nhỏ hơn và không phải database
runtime của backend. Các test P2 dùng SQLite fixture, không ghi dữ liệu restore.

## Ma trận test P2

| ID | Phạm vi | Case chức năng/nghiệp vụ và kết quả mong đợi | Trạng thái |
|---|---|---|---:|
| SV-01 | Customer segment | Lưu segment theo nhiều tag, chế độ `all`, truy vấn đúng thành viên và chỉ trong tenant | PASS |
| SV-02 | Saved view tổng quát | Lưu bộ lọc/cột/sắp xếp cho inbox, orders, tickets; mở lại giữ nguyên cấu hình | GAP — chưa có model/API/UI |
| BULK-01 | Bulk actions | Chọn nhiều bản ghi, kiểm tra quyền, cập nhật atomically và báo lỗi từng phần | GAP — chưa có endpoint/UI |
| BULK-02 | Bulk safety | Replay/idempotency, audit và không vượt tenant khi thao tác hàng loạt | GAP — chưa có implementation để test |
| WF-01 | Workflow builder | Tạo/sửa/bật-tắt workflow với event, condition và action hợp lệ | PASS |
| WF-02 | Validation | Event/action không được hỗ trợ bị từ chối 422 | PASS |
| WF-03 | Conditions | Event không khớp điều kiện bị `skipped`, không tạo ticket/tag | PASS |
| WF-04 | Idempotency | Gửi cùng `event_id` lần hai trả `duplicate`, không tạo side effect lần hai | PASS |
| WF-05 | Durable scheduling | Delay tạo `CrmJob` và `WorkflowRun` scheduled; worker dispatch chuyển run sang terminal state | PASS |
| WF-06 | Dispatch response | Endpoint dispatch trả đúng các run vừa xử lý và lần gọi lại không xử lý trùng | PASS — đã sửa lỗi |
| WF-07 | Retry | Job lỗi vẫn retryable; retry chỉ được phép với run `failed` | PASS |
| WF-08 | Tenant isolation | Tenant khác không list/get/run workflow hoặc đọc run của tenant này | PASS |
| SHIP-01 | Vận chuyển nội bộ | Lưu provider/tracking/status hợp lệ, tạo `logistics_updated` event; status sai bị 422 | PASS |
| SHIP-02 | Đơn hàng | Metadata logistics đi cùng lịch sử order, không làm đổi trái phép lifecycle/payment | PASS |
| SHIP-03 | Hãng vận chuyển thật | Tạo vận đơn, lấy trạng thái, retry webhook và đối soát phí với GHN/GHTK/VNPost | GAP — mới có metadata, chưa có adapter/provider |
| PAY-01 | Payment nội bộ | Thanh toán một phần/đủ, chặn overpay, idempotency và audit event | PASS |
| PAY-02 | Refund nội bộ | Refund bounded, idempotent; full refund cập nhật payment/order và khôi phục tồn kho đúng nghiệp vụ | PASS |
| PAY-03 | Gateway thật | Checkout, webhook chữ ký, settlement, chargeback/refund và đối soát gateway | GAP — chưa chọn/cấu hình provider |
| INV-01 | Nhập hàng | Receipt một phần, chặn nhận vượt số lượng, idempotency và cập nhật tồn kho | PASS |
| INV-02 | Hóa đơn | Phát hành/hủy/điều chỉnh hóa đơn điện tử, mã số thuế và retry provider | GAP — chưa có invoice adapter/model |
| AG-01 | Agency multi-shop | Một agency quản lý nhiều shop, role theo shop, báo cáo tổng hợp và chặn cross-shop | GAP — chưa có agency/control-plane model |
| WL-01 | White-label | Brand/logo/domain/theme/email sender riêng theo shop, không rò branding sang tenant khác | GAP — chưa có cấu hình white-label |
| SCH-01 | Schema registry | Tên schema deterministic; trạng thái `proposed → ready → disabled`, bật feature sai state bị chặn; thao tác lặp idempotent | PASS |
| SCH-02 | Schema vật lý | `CREATE SCHEMA`, migrate/copy dữ liệu, route session, RLS, cutover và rollback độc lập từng tenant | GAP — code hiện chỉ là registry pilot, chưa tạo schema/chuyển dữ liệu |

## Lỗi tìm thấy và đã sửa

1. `POST /api/workflows/runs/dispatch` lấy các run có trạng thái `scheduled` sau khi
   job handler đã chuyển chúng sang `completed`/`failed`, nên response rỗng dù job đã
   chạy thành công. Endpoint nay chụp `run_id` trước dispatch và trả lại đúng các run đó.
2. Test workflow phụ thuộc số ticket tuyệt đối trong database dùng chung, dễ fail theo
   thứ tự test. Assertion đã chuyển sang kiểm tra delta `before + 1`.
3. Assertion frontend P2 dùng tên hàm thanh toán không tồn tại; đã sửa theo contract
   thực tế `recordSalesPayment` và route `refunds`. Đây là lỗi của test harness, không
   phải lỗi runtime.
4. Route Shopee bị ghép prefix hai lần thành
   `/api/webhooks/shopee/webhooks/shopee`; router nay chỉ công bố
   `/api/webhooks/shopee`.
5. Dispatch workflow từng là side effect qua `GET`; endpoint đã chuyển sang `POST`,
   yêu cầu quyền ghi và có contract test ngăn regression.

## Phạm vi chưa thể chứng nhận

Các GAP ở trên cần thiết kế và triển khai trước khi gọi P2 “done”. Đặc biệt, schema
registry hiện chỉ cho phép rehearsal rollout; nó **không** chứng minh database/schema
riêng đã được tạo hoặc dữ liệu đã được chuyển. Tương tự, logistics/payment hiện là
ledger và metadata nội bộ; chưa phải tích hợp production với bên thứ ba.

Không có dữ liệu hội thoại/khách hàng production nào bị thay đổi bởi vòng test này.
