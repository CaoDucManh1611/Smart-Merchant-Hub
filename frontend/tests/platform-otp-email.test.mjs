import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import * as Vue from 'vue';
import { renderToString } from '@vue/server-renderer';
import { parse, compileScript, compileTemplate, compileStyle } from '@vue/compiler-sfc';

const { descriptor, errors } = parse(readFileSync(new URL('../src/PlatformOtpEmail.vue', import.meta.url), 'utf8'));
const saved = { enabled: true, username: 'sender@example.test', from_email: 'sender@example.test', from_name: 'Test sender', password_configured: true };
const reply = (body, ok = true) => ({ ok, json: async () => body });
function fixture(fetch) {
  let mounted;
  const context = vm.createContext({ ref: Vue.ref, onMounted: fn => { mounted = fn; }, defineProps: () => ({ apiBase: '/api' }), apiFetch: fetch });
  vm.runInContext(descriptor.scriptSetup.content.replace(/^import .*;\s*$/gm, '') + '\nglobalThis.state = {config,password,busy,loaded,error,notice,load,save};', context);
  return { state: context.state, mount: () => mounted() };
}
async function render(state) {
  const compiled = compileTemplate({ source: descriptor.template.content, filename: 'PlatformOtpEmail.vue', id: 'otp-test', compilerOptions: { mode: 'function' } });
  assert.deepEqual(compiled.errors, []);
  const renderFn = vm.runInNewContext(`(function () { ${compiled.code}\n})()`, { Vue });
  return renderToString(Vue.createSSRApp({ setup: () => state, render: renderFn }));
}

test('OTP component compiles with installed Vue', () => {
  assert.deepEqual(errors, []);
  assert.ok(compileScript(descriptor, { id: 'otp-test' }).content);
  assert.deepEqual(compileStyle({ source: descriptor.styles[0].content, filename: 'PlatformOtpEmail.vue', id: 'otp-test', scoped: true }).errors, []);
});
test('save clears password and reload never populates it from saved metadata', async () => {
  const calls = [];
  const { state, mount } = fixture(async (url, init) => { calls.push({ url, ...init }); return reply({ ...saved }); });
  await mount(); state.password.value = 'FAKE-TEST-ONLY'; await state.save();
  assert.equal(calls[1].method, 'PUT'); assert.equal(calls[1].url, '/api/platform/otp-email');
  assert.equal(JSON.parse(calls[1].body).password, 'FAKE-TEST-ONLY');
  assert.equal(state.password.value, ''); assert.ok(state.notice.value);
  await state.load(); assert.equal(calls[2].method, 'GET'); assert.equal(calls[2].body, undefined);
  assert.equal(state.password.value, ''); assert.equal(Object.hasOwn(state.config.value, 'password'), false);
  assert.doesNotMatch(await render(state), /FAKE-TEST-ONLY/);
});
test('failed save clears password, renders alert and releases busy controls', async () => {
  let release;
  const { state } = fixture(() => new Promise(resolve => { release = resolve; }));
  state.loaded.value = true; state.config.value = { ...saved }; state.password.value = 'FAKE-TEST-ONLY';
  const saving = state.save(); assert.equal(state.busy.value, true);
  const busyHtml = await render(state); assert.match(busyHtml, /<fieldset disabled/);
  assert.doesNotMatch(busyHtml, /Gửi email thử/);
  release(reply({ detail: 'Cấu hình chưa hợp lệ.' }, false)); await saving;
  assert.equal(state.password.value, ''); assert.equal(state.busy.value, false); assert.equal(state.notice.value, '');
  const html = await render(state); assert.match(html, /role="alert"/); assert.match(html, /Cấu hình chưa hợp lệ/);
  assert.doesNotMatch(html, /<fieldset disabled|FAKE-TEST-ONLY/);
});
test('failed initial load shows retry and hides forms', async () => {
  const { state, mount } = fixture(async () => { throw new Error('Không thể tải cấu hình.'); });
  await mount(); assert.equal(state.loaded.value, false); assert.equal(state.busy.value, false);
  const html = await render(state); assert.match(html, /role="alert"/); assert.match(html, /Tải lại/); assert.doesNotMatch(html, /<form/);
});
test('test email controls are removed while SMTP configuration remains', async () => {
  const { state } = fixture(async () => reply({ ...saved })); state.loaded.value = true;
  const html = await render(state);
  for (const label of ['Gmail gửi', 'Email người gửi', 'Tên người gửi', 'Mật khẩu ứng dụng Gmail']) assert.ok(html.includes(`<label>${label}<input`), label);
  assert.doesNotMatch(html, /Email nhận thử|Gửi email thử|otp-email-test/);
  assert.match(html, /type="password"[^>]*autocomplete="new-password"/); assert.match(html, /aria-describedby="otp-password-help"/); assert.match(html, /id="otp-password-help"/);
  assert.match(html, /Lưu cấu hình email/);
});
