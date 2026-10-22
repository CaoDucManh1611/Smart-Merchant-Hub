import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const source = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8');
test('webhook redesign preserves status refresh and connection navigation', () => {
  const start = source.indexOf('<section v-if="currentTab === \'webhooks\'"');
  const view = source.slice(start, source.indexOf('</section>', start));
  assert.match(view, /@click="refreshWebhookStatus"/);
  assert.match(view, /:disabled="botConnectionLoading \|\| metaLoading"/);
  assert.match(view, /@click="openChannels"/);
  assert.match(view, /v-for="platform in webhookPlatformStatuses"/);
  assert.match(view, /platform.active \? 'Đang hoạt động' : platform.disconnected \? 'Đã ngắt' : 'Không hoạt động'/);
  for (const channel of ['facebook', 'instagram', 'telegram', 'zalo', 'tiktok', 'shopee']) {
    assert.match(source, new RegExp(`channel_type: "${channel}"`));
  }
  assert.match(source, /const active = isSocialChannelOnline\(platform\.channel_type\)/);
  assert.match(source, /item\.webhook_status === "disconnected"/);
  assert.match(source, /item\.webhook_status === "disconnected"/);
  assert.doesNotMatch(view, /'Cần kiểm tra'|'Đã kết nối'|'Chưa kết nối'|điểm nhận sự kiện|mã bảo vệ|Tin không hợp lệ|Thử lại không tạo/);
  assert.match(view, /<h2>\{\{ t\('Trạng thái nhận tin'\) \}\}<\/h2>/);
  assert.match(source, /metaStatus\.value\.connected && metaStatus\.value\.instagram_account_id/);
  assert.match(view, /class="webhook-heading-icon" aria-hidden="true"/);
});
test('webhook typography and responsive cards have a reduced-motion alternative', () => {
  assert.match(source, /\.webhooks-layout \.webhook-item strong \{ font-size: 18px;/);
  assert.match(source, /\.webhooks-layout \.webhook-item small \{ font-size: 14px;/);
  assert.match(source, /@media \(max-width: 760px\) \{ \.webhooks-layout \.webhook-checklist \{ grid-template-columns: 1fr;/);
  assert.match(source, /@media \(prefers-reduced-motion: reduce\) \{ \.webhooks-layout \.webhook-card:first-child, \.webhook-refresh \.is-refreshing \{ animation: none;/);
});
