import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
test('support tickets start collapsed with a summary and retain their response form', () => {
  const source = readFileSync(new URL('../src/PlatformSupport.vue', import.meta.url), 'utf8');
  assert.match(source, /<details v-for="item in items"[^>]*class="support-admin-ticket">/);
  assert.match(source, /<summary class="support-ticket-summary">/);
  assert.match(source, /class="support-ticket-preview"/);
  assert.match(source, /<textarea v-model="drafts\[item.id\]"/);
});
test('admin support sends a single multi-channel ticket response through the platform API', async () => {
  const source = readFileSync(new URL('../src/PlatformSupport.vue', import.meta.url), 'utf8');
  const calls = [];
  const context = { props: { baseUrl: '/api', adminId: 9, request: async (url, options) => { calls.push({ url, ...options }); return { ok: true, json: async () => ({ id: 12, status: 'in_progress' }) }; } }, saving: { value: null }, error: { value: '' }, notice: { value: '' }, drafts: { value: { 12: 'Đội hỗ trợ đã nhận yêu cầu.' } }, items: { value: [{ id: 12 }] } };
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('async function update('), source.indexOf('\nasync function page(')), context);
  await context.update({ id: 12 }, 'in_progress');
  assert.equal(calls[0].url, '/api/platform/support-requests/12');
  assert.deepEqual(JSON.parse(calls[0].body), { status: 'in_progress', assigned_admin_id: 9, response: 'Đội hỗ trợ đã nhận yêu cầu.' });
  assert.equal(context.saving.value, null);
  assert.equal(context.drafts.value[12], '');
  assert.match(source, /item.providers \|\| \[item.provider\]/);
  assert.match(source, /resolved: \['in_progress', 'closed'\], closed: \[\]/);
});
