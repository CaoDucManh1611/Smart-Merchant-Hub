import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import * as Vue from 'vue';
import { parse, compileScript, compileTemplate } from '@vue/compiler-sfc';
import { renderToString } from '@vue/server-renderer';
const saved = { enabled: true, bank_bin: '970436', account_number: '000123', account_name: 'TEST ONLY', bank_name: 'Test bank', bank_options: [{ bin: '970436', name: 'Test bank' }] };
const reply = (body, ok = true) => ({ ok, json: async () => body });
function fixture(fetch) {
  const { descriptor, errors } = parse(readFileSync(new URL('../src/PlatformPaymentSettings.vue', import.meta.url), 'utf8'));
  assert.deepEqual(errors, []); compileScript(descriptor, { id: 'payment-test' });
  const context = vm.createContext({ ref: Vue.ref, onMounted: () => {}, defineProps: () => ({ apiBase: '/api' }), apiFetch: fetch });
  vm.runInContext(descriptor.scriptSetup.content.replace(/^import .*;\s*$/gm, '') + '\nglobalThis.state={config,busy,loaded,error,notice,load,save,checkConfiguration};', context);
  const compiled = compileTemplate({ source: descriptor.template.content, filename: 'PlatformPaymentSettings.vue', id: 'payment-test', compilerOptions: { mode: 'function' } });
  assert.deepEqual(compiled.errors, []);
  const render = vm.runInNewContext(`(function(){${compiled.code}\n})()`, { Vue });
  return { state: context.state, html: () => renderToString(Vue.createSSRApp({ setup: () => context.state, render })) };
}
test('VietQR settings load banks and PUT only primary receiving-account fields, including legacy GET compatibility', async () => {
  const calls=[];
  const f=fixture(async(url,init)=>{calls.push({url,...init});return reply({...saved,client_id:'legacy',api_key_configured:true});});
  await f.state.load(); const html=await f.html();
  assert.match(html, /<select/); assert.match(html, /Test bank/); assert.doesNotMatch(html, /type="password"|Client ID|Checksum|payOS|webhook/);
  await f.state.save(); assert.equal(calls[1].method,'PUT'); assert.equal(calls[1].url,'/api/platform/payment-settings');
  assert.deepEqual(JSON.parse(calls[1].body),{enabled:true,bank_bin:'970436',account_number:'000123',account_name:'TEST ONLY'});
});
test('legacy receiving bank remains selectable when bank_options is absent', async()=>{
  const f=fixture(async()=>reply({enabled:true,bank_bin:'970999',account_number:'001',account_name:'LEGACY'}));
  await f.state.load(); assert.match(await f.html(), /value="970999"/);
});
test('failed save preserves receiving-account draft and releases disabled controls',async()=>{
  let release;const f=fixture(()=>new Promise(resolve=>{release=resolve;}));
  f.state.loaded.value=true;f.state.config.value={...saved};const saving=f.state.save();
  assert.match(await f.html(),/<fieldset disabled/);release(reply({},false));await saving;
  assert.equal(f.state.config.value.account_number,'000123');assert.equal(f.state.busy.value,false);assert.match(await f.html(),/role="alert"/);
});
test('local configuration check sends no bank/provider request payload and makes no verification claim',async()=>{
  const calls=[];const f=fixture(async(url,init)=>{calls.push({url,...init});return reply({status:'configured'});});
  f.state.loaded.value=true;f.state.config.value={...saved};await f.state.checkConfiguration();
  assert.equal(calls[0].method,'POST');assert.equal(calls[0].url,'/api/platform/payment-settings/test');assert.deepEqual(JSON.parse(calls[0].body),{});
  assert.match(await f.html(),/VietQR/);assert.ok(f.state.notice.value.includes('không xác minh'));
});
test('checkout uses server QR payload and frozen amount; manual confirmation only, historical payOS retained',()=>{
  const source=readFileSync(new URL('../src/ServiceCheckout.vue',import.meta.url),'utf8');
  assert.match(source,/QRCode.toDataURL\(code/);assert.match(source,/formatMoney\(payment.amount\)/);
  assert.match(source,/VietQR/);assert.match(source,/admin xác nhận thực nhận tiền/);
  assert.match(source,/pay.payos.vn/);assert.match(source,/payment.provider !== 'vietqr'/);
  assert.doesNotMatch(source,/emit\(['"]paid|confirmPayment|markPaid/);
});
