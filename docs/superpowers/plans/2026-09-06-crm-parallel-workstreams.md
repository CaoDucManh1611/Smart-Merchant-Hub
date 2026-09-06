# CRM Next Phase — Kế hoạch 2 luồng song song

> Tài liệu kế hoạch này chưa được commit. Chỉ commit khi chủ repo yêu cầu.

**Mục tiêu:** hoàn thiện các khoảng trống vận hành còn lại của CRM trên nhánh `crm-completion`, chia thành hai luồng độc lập để có thể làm song song và merge an toàn.

**Nền tảng hiện tại:** nhánh `crm-completion` đã có Customer 360, đơn bán/đơn nhập, tồn kho, thanh toán nội bộ, ticket, báo cáo, auth/audit và đa kênh. Hai luồng dưới đây chỉ tập trung vào CRM; RAG, auto-reply và workflow do chủ repo tự xử lý ở đợt khác.

**Nguyên tắc chung:** mọi truy vấn phải tenant-scoped; không log token/nội dung nhạy cảm; dùng TDD; không force-push; không tự commit hoặc merge nếu chủ repo chưa yêu cầu.

---

## Luồng A — CRM Operations: Customer 360, CSKH và quyền

### Phạm vi file

- Backend Customer 360: `backend/app/api/customers.py`, `backend/app/services/customer_profile.py`, `backend/app/services/customer_identity.py`, `backend/app/services/customer_merge_service.py`, `backend/app/schemas/customer.py`, `backend/app/schemas/customer_merge.py`.
- Backend CSKH/quyền: `backend/app/api/tickets.py`, `backend/app/api/team.py`, `backend/app/api/auth.py`, `backend/app/services/audit_service.py`, `backend/app/auth/`.
- Test tương ứng: `backend/tests/test_customer_360_api.py`, `backend/tests/test_customer_360_final.py`, `backend/tests/test_customer_merge_api.py`, `backend/tests/test_customer_tags_api.py`, `backend/tests/test_cskh_advanced_api.py`, `backend/tests/test_auth_api.py`, `backend/tests/test_team_api.py`, `backend/tests/test_security_hardening.py`.

### Đầu việc

- [x] Chốt API gợi ý khách trùng: điểm trùng phải giải thích được theo tên/email/số điện thoại/identity, có ngưỡng tối thiểu và không trả khách khác tenant.
- [x] Hoàn thiện lọc nhiều tag với hai chế độ `all` và `any`, hỗ trợ segment đã lưu, phân trang ổn định và tổng số bản ghi chính xác.
- [x] Hoàn thiện merge/undo merge an toàn: hiển thị preview trước khi gộp, lưu snapshot, không gộp lần hai, undo không làm mất dữ liệu phát sinh sau merge và ghi audit event.
- [x] Bổ sung lịch sử Customer 360 đầy đủ: identity, message, note, tag, fact, ticket, order và merge event; các event phải có thời gian, nguồn và liên kết bản ghi.
- [x] Hoàn thiện CSKH: comment ticket, lịch sử xử lý, SLA notification, gán lại conversation/ticket; mọi thao tác ghi yêu cầu role phù hợp và ghi audit log.
- [x] Kiểm tra auth/team: owner/admin/agent/viewer đúng quyền đọc/ghi, session hết hạn và tenant isolation; không dùng header tenant thay cho bearer session ở production.

### Tiêu chí nghiệm thu

- Test gợi ý trùng, lọc tag `all/any`, merge/undo, timeline và tenant isolation đều đạt.
- Ticket có thể tạo comment, xem lịch sử, nhận cảnh báo quá SLA và gán lại; viewer không thể ghi.
- Auth/audit test không phát hiện credential hoặc token trong log; không truy cập chéo tenant.

### Lệnh kiểm tra

```powershell
cd backend
$env:PYTHONPATH = "$PWD\.migrationdeps;$PWD"
& 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_customer_360_api.py tests/test_customer_360_final.py tests/test_customer_merge_api.py tests/test_customer_tags_api.py tests/test_cskh_advanced_api.py tests/test_auth_api.py tests/test_team_api.py tests/test_security_hardening.py -q
```

---

## Luồng B — Sales/Purchase Operations, tồn kho và báo cáo

### Phạm vi file

- Backend Sales/Purchase: `backend/app/api/sales.py`, `backend/app/api/purchase_orders.py`, `backend/app/api/suppliers.py`, `backend/app/api/inventory.py`, `backend/app/api/payments.py`, `backend/app/services/order_service.py`, `backend/app/services/inventory_service.py`, `backend/app/models/order_event.py`, `backend/app/models/order_payment.py`, `backend/app/models/purchase_order.py`.
- Backend reports: `backend/app/api/reports.py`, `backend/app/schemas/sales.py`, `backend/app/schemas/purchase_order.py`, `backend/app/schemas/inventory.py`.
- Frontend: `frontend/src/App.vue`, `frontend/src/style.css`, `frontend/tests/orders-p1-02.test.mjs`; luồng này là luồng duy nhất chỉnh phần Orders/Purchase/Reports trong `App.vue` để tránh conflict.
- Test tương ứng: `backend/tests/test_order_lifecycle.py`, `backend/tests/test_order_payments.py`, `backend/tests/test_purchase_order_api.py`, `backend/tests/test_sales_inventory_lifecycle.py`, `backend/tests/test_inventory_receiving.py`, `backend/tests/test_reports_api.py`, `backend/tests/test_p1_02_timeline_reports.py`.

### Đầu việc

- [ ] Hoàn thiện vòng đời Sales Order: transition hợp lệ, giữ/xuất/giải phóng tồn, chống tồn âm và phản ánh event vào Customer 360.
- [ ] Hoàn thiện Purchase Order: supplier snapshot, nhận hàng từng phần/nhiều lần, idempotency, cộng tồn và trạng thái công nợ.
- [ ] Hoàn thiện thanh toán/hoàn tiền nội bộ: unpaid/partial/paid, chống overpayment, idempotency và ledger đối soát được.
- [ ] Hoàn thiện báo cáo CRM: doanh thu theo kênh, tồn thực tế/đang giữ/có thể bán, chi phí nhập theo supplier/thời gian và hiệu suất xử lý.
- [ ] Kiểm tra UI Orders/Purchase/Reports: đổi trạng thái, thu/hoàn, nhận hàng, lịch sử đơn, chọn conversation và cuộn trang; giữ logo Smart Merchant Hub, không đưa branding đồ ăn trở lại.

### Tiêu chí nghiệm thu

- Không thể đổi trạng thái đơn bằng đường PATCH thông thường; mọi transition dùng endpoint nghiệp vụ và ghi event.
- Xác nhận Sales Order cập nhật reservation, shipped cập nhật on-hand, hủy/hoàn tiền cập nhật ledger chính xác.
- Purchase receipt lặp cùng idempotency key không cộng tồn hai lần; nhận một phần phản ánh đúng status và công nợ.
- Báo cáo và Customer 360 chỉ hiển thị dữ liệu đúng tenant/kênh; frontend tests và build Docker đạt.

### Lệnh kiểm tra

```powershell
cd backend
$env:PYTHONPATH = "$PWD\.migrationdeps;$PWD"
& 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_order_lifecycle.py tests/test_order_payments.py tests/test_purchase_order_api.py tests/test_sales_inventory_lifecycle.py tests/test_inventory_receiving.py tests/test_reports_api.py tests/test_p1_02_timeline_reports.py -q
cd ..\frontend
node --test tests/orders-p1-02.test.mjs tests/crm-shell.test.mjs tests/crm-theme.test.mjs
```

---

## Quy trình tách nhánh, kiểm tra và merge

1. Từ commit hiện tại của `crm-completion`, tạo hai nhánh: `crm-customer-ops` và `crm-commerce-ops`.
2. Mỗi người chỉ sửa các file thuộc luồng của mình; nếu buộc phải sửa file dùng chung thì ghi rõ trong pull request và phối hợp trước.
3. Mỗi luồng chạy test riêng, sau đó chạy lại toàn bộ backend/frontend trên nhánh của mình.
4. Chỉ khi chủ repo yêu cầu mới commit và push hai nhánh; không force-push.
5. Merge lần lượt vào `crm-completion`, ưu tiên Luồng A trước; Luồng B là luồng duy nhất chỉnh Orders/Purchase/Reports trong `App.vue`; xử lý conflict bằng cách giữ contract hiện tại và chạy lại toàn bộ test.
6. Sau merge, kiểm tra `git diff --check`, migration head, frontend build Docker và smoke test webhook/order trước khi cân nhắc đưa lên `main`.

## Ngoài phạm vi đợt này

- Cổng thanh toán thực tế/đối soát ngân hàng.
- Nhiều kho, lô/hạn sử dụng, serial number và vận chuyển bên thứ ba.
- RAG, auto-reply và workflow do chủ repo xử lý riêng.
- Recommendation/ML, A/B testing và Bandit chỉ làm sau khi hai luồng CRM trên ổn định.
