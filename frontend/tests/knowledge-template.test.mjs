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
  for (const content of ['HƯỚNG DẪN ĐIỀN', 'Mã SKU:', 'Link sản phẩm:', 'Màu sắc / phiên bản:', 'CÂU HỎI THƯỜNG GẶP', 'CHÍNH SÁCH GIAO HÀNG', 'ĐỔI TRẢ VÀ BẢO HÀNH', 'UTF-8']) {
    assert.ok(template.includes(content), content);
  }
});
