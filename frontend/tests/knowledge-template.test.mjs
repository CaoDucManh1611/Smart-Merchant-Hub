import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

test('knowledge template is downloadable without triggering the upload picker', () => {
  const source = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8');
  const link = source.match(/<a[^>]*href="\/templates\/tai-lieu-mau-kho-kien-thuc.txt"[^>]*>/)?.[0];
  assert.ok(link);
  assert.match(link, /download="tai-lieu-mau-kho-kien-thuc.txt"/);
  assert.match(link, /@click.stop @keydown.stop/);
  assert.doesNotMatch(link, /disabled|knowledgeDocumentQuotaReached/);
  const template = readFileSync(new URL('../public/templates/tai-lieu-mau-kho-kien-thuc.txt', import.meta.url), 'utf8');
  for (const content of ['PHẠM VI VÀ HIỆU LỰC', 'Mã SKU đối chiếu CRM:', 'HÀNG HÓA', 'DỊCH VỤ ĐẶT LỊCH', 'TÀI SẢN CHO THUÊ', 'CÂU HỎI THƯỜNG GẶP', 'GIAO HÀNG/BÀN GIAO/THỰC HIỆN', 'ĐỔI TRẢ, HỦY VÀ HOÀN TIỀN', 'UTF-8', 'gửi trước nhân viên xác nhận đơn', 'không tự tạo hóa đơn']) {
    assert.ok(template.includes(content), content);
  }
});
