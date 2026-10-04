import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
const source = fs.readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8');
test('pricing signup carries the selected plan and service type through OTP verification', () => {
  assert.match(source, /openSignup\(true\)/);
  assert.match(source, /plan_code: signupPlanCode\.value, service_type: signupServiceType\.value/);
});
test('admin billing uses backend data and requires explicit receipt confirmation', () => {
  assert.match(source, /platform\/billing-summary/);
  assert.match(source, /platformBilling\.net_collected/);
  assert.match(source, /requestConfirmation\(`Bạn xác nhận đã thực nhận/);
  assert.match(source, /provider_transaction_id: draft\.reference\.trim\(\)/);
});
