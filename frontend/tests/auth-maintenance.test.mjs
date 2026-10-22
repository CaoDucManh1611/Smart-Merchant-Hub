import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import test from 'node:test';

const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8');
const source = app.slice(app.indexOf('async function loadAuthSession()'), app.indexOf('function timelineExplainability('));
function session(status) {
  const state = { authToken: { value: 'existing-session' }, authUser: { value: null }, API_BASE: '/api', retry: null, cleared: false,
    apiFetch: async () => ({ ok: status === 200, status, json: async () => ({ id: 1 }) }),
    fetchSecuritySettings: async () => {}, fetchQuotaUsage: async () => {},
  };
  state.clearAuthToken = () => { state.cleared = true; };
  state.setTimeout = callback => { state.retry = callback; };
  runInNewContext(source, state);
  return state;
}
test('maintenance preserves the session and loads it after the server recovers', async () => {
  const state = session(503);
  await state.loadAuthSession();
  assert.equal(state.cleared, false);
  assert.equal(state.authToken.value, 'existing-session');
  assert.equal(typeof state.retry, 'function');
  state.apiFetch = async () => ({ ok: true, json: async () => ({ id: 1 }) });
  state.retry();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(state.authUser.value.id, 1);
});
test('an expired session still clears authentication', async () => {
  const state = session(401);
  await state.loadAuthSession();
  assert.equal(state.cleared, true);
  assert.equal(state.authToken.value, '');
  assert.equal(state.retry, null);
});
