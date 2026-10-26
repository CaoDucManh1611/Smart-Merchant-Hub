import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { ref, computed, watch, effectScope, nextTick } from 'vue';

const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8');
function appFunction(name) {
  const start = app.indexOf(`function ${name}(`);
  assert.notEqual(start, -1);
  const prefix = app.slice(start - 6, start) === 'async ' ? 'async ' : '';
  return prefix + app.slice(start, app.indexOf('\n}', start) + 2);
}

function checkout(t, storage = new Map(), businessId = 1) {
  const state = {
    ref, computed, watch,
    authUser: ref({ business_id: businessId, full_name: 'Owner' }),
    activeServicePlans: ref(['demo', 'starter', 'growth', 'scale', 'pro'].map(code => ({ code }))),
    tenantReady: ref(false), currentTab: ref('inbox'), API_BASE: '/api',
    SERVICE_CHANNELS: ['Facebook', 'Instagram', 'Telegram', 'Zalo', 'TikTok', 'Shopee'],
    serviceChannelLimit: ref(6),
    window: { sessionStorage: {
      getItem: key => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, value),
    } },
    requireBusinessId: user => user.business_id,
    friendlyErrorMessage: (_, fallback) => fallback,
    apiResponseError: () => new Error('request failed'),
    subscriptionStatusLabel: status => status,
    loadServicePayment: async () => {},
    apiFetch: async () => ({ ok: true, json: async () => ({}) }),
  };
  for (const name of ['serviceAccountSummary', 'quotaSnapshot', 'serviceCheckoutRequest', 'servicePayment']) state[name] = ref(null);
  for (const name of ['servicePlanSelectionTouched', 'serviceRequestSubmitted', 'serviceCheckoutOpen', 'serviceAccountLoading', 'quotaLoading']) state[name] = ref(false);
  for (const name of ['serviceRequestReference', 'servicePaymentError', 'serviceRequestError', 'serviceRequestNotice', 'servicePurchaseNotice', 'servicePurchaseError', 'servicePurchaseStatus', 'serviceAccountError', 'quotaError']) state[name] = ref('');
  state.serviceMode = ref('package');
  state.serviceRequestForm = ref({ plan_code: 'growth', channels: [] });
  state.selectedServicePlan = computed(() => state.activeServicePlans.value.find(plan => plan.code === state.serviceRequestForm.value.plan_code));
  vm.createContext(state);
  const current = app.slice(app.indexOf('const currentServicePlanCode = computed('), app.indexOf('const currentServicePlan = computed('));
  const watcherStart = app.indexOf('watch(() => authUser.value?.business_id,');
  const watcher = app.slice(watcherStart, app.indexOf('function openServicePage()', watcherStart));
  const functions = ['servicePlanCodeForPurchase', 'preferredServicePlanCode', 'servicePlanSelectionStorageKey', 'readServicePlanSelection', 'saveServicePlanSelection', 'resetServiceRequestForm', 'normalizeServiceChannels', 'selectServicePlan', 'fetchServiceAccountSummary', 'fetchQuotaUsage'].map(appFunction).join('\n');
  const scope = effectScope();
  scope.run(() => vm.runInContext(`${current}\n${functions}\n${watcher}\nglobalThis.currentPlan = currentServicePlanCode;`, state));
  t.after(() => scope.stop());
  return state;
}

test('Premium draft survives F5 and late subscription/usage responses', async t => {
  const storage = new Map();
  const first = checkout(t, storage);
  first.serviceAccountSummary.value = {};
  first.selectServicePlan('pro');
  const refreshed = checkout(t, storage);
  assert.equal(refreshed.serviceRequestForm.value.plan_code, 'pro');
  refreshed.tenantReady.value = true;
  refreshed.apiFetch = async url => ({ ok: true, json: async () => url.endsWith('/usage')
    ? { plan_code: 'growth' }
    : { subscription: { plan_code: 'growth', status: 'active' } } });
  await Promise.all([refreshed.fetchQuotaUsage(), refreshed.fetchServiceAccountSummary()]);
  assert.equal(refreshed.serviceRequestForm.value.plan_code, 'pro');
  assert.equal(refreshed.currentPlan.value, 'growth');
  assert.deepEqual(JSON.parse(storage.get('crm-service-selection-1')), { mode: 'package', plan_code: 'pro' });
});

test('server restores pending Premium before tenant provisioning, without purchasing again', async t => {
  for (const status of ['awaiting_payment', 'pending']) {
    const state = checkout(t);
    let calls = 0;
    state.apiFetch = async () => {
      calls++;
      return { ok: true, json: async () => ({ subscription: { plan_code: 'starter', status: 'active' }, package_request: { plan_code: 'pro', status } }) };
    };
    await state.fetchServiceAccountSummary();
    assert.equal(state.serviceRequestForm.value.plan_code, 'pro');
    assert.equal(state.currentPlan.value, 'starter');
    assert.equal(state.serviceCheckoutRequest.value, null);
    assert.equal(calls, 1);
  }
});

test('opening pricing after session bootstrap loads the saved server request automatically', async t => {
  const state = checkout(t);
  state.apiFetch = async () => ({ ok: true, json: async () => ({ package_request: { plan_code: 'pro', status: 'awaiting_payment' } }) });
  state.currentTab.value = 'service';
  await nextTick();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(state.serviceRequestForm.value.plan_code, 'pro');
  assert.equal(state.tenantReady.value, false);
});

test('shop plan selections remain isolated across accounts and reloads', t => {
  const storage = new Map();
  const state = checkout(t, storage);
  state.serviceAccountSummary.value = {};
  state.selectServicePlan('pro');
  state.authUser.value = { business_id: 2 };
  assert.equal(state.serviceRequestForm.value.plan_code, 'growth');
  assert.equal(state.serviceCheckoutOpen.value, false);
  const refreshed = checkout(t, storage, 2);
  assert.equal(refreshed.serviceMode.value, 'package');
  assert.equal(refreshed.serviceRequestForm.value.plan_code, 'growth');
  refreshed.serviceAccountSummary.value = {};
  refreshed.selectServicePlan('scale');
  const refreshedAgain = checkout(t, storage, 2);
  assert.equal(refreshedAgain.serviceRequestForm.value.plan_code, 'scale');
  state.authUser.value = { business_id: 1 };
  assert.equal(state.serviceMode.value, 'package');
  assert.equal(state.serviceRequestForm.value.plan_code, 'pro');
});

test('cancelled and expired requests cannot replace the active plan', async t => {
  for (const status of ['cancelled', 'expired']) {
    const state = checkout(t);
    state.apiFetch = async () => ({ ok: true, json: async () => ({ subscription: { plan_code: 'scale', status: 'active' }, package_request: { plan_code: 'pro', status } }) });
    await state.fetchServiceAccountSummary();
    assert.equal(state.serviceRequestForm.value.plan_code, 'scale');
  }
});

test('without a draft or pending request, pricing selects the assigned subscription', async t => {
  const state = checkout(t);
  state.apiFetch = async () => ({ ok: true, json: async () => ({ subscription: { plan_code: 'scale', status: 'active' }, chatbot_subscription: { plan_code: 'pro', status: 'active' } }) });
  await state.fetchServiceAccountSummary();
  assert.equal(state.serviceRequestForm.value.plan_code, 'scale');
});

test('corrupt or unavailable browser storage does not break checkout', t => {
  for (const value of ['bad JSON', '{"mode":"package","plan_code":"unknown"}', '{"mode":"invalid","plan_code":"pro"}']) {
    const state = checkout(t, new Map([['crm-service-selection-1', value]]));
    assert.equal(state.serviceRequestForm.value.plan_code, 'growth');
  }
  const state = checkout(t);
  state.serviceAccountSummary.value = {};
  state.window.sessionStorage.getItem = state.window.sessionStorage.setItem = () => { throw new Error('blocked'); };
  assert.doesNotThrow(() => state.resetServiceRequestForm());
  assert.doesNotThrow(() => state.selectServicePlan('pro'));
  assert.equal(state.serviceRequestForm.value.plan_code, 'pro');
});

test('a delayed response from another shop cannot change the selected plan', async t => {
  const state = checkout(t);
  let finish;
  state.apiFetch = () => new Promise(resolve => { finish = resolve; });
  const pending = state.fetchServiceAccountSummary();
  state.authUser.value = { business_id: 2 };
  finish({ ok: true, json: async () => ({ package_request: { plan_code: 'pro', status: 'pending' } }) });
  await pending;
  assert.equal(state.serviceAccountSummary.value, null);
  assert.equal(state.serviceRequestForm.value.plan_code, 'growth');
});
