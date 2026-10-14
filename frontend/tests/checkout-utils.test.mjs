import test from 'node:test';
import assert from 'node:assert/strict';
import { planChangeKind, checkoutRequestLabel, checkoutAmount } from '../src/checkout-utils.js';

test('checkout never replaces a frozen payment or quote with a changed catalogue price', () => {
  assert.equal(checkoutAmount(1000, { amount: 1000 }, 2000), 1000);
  assert.equal(checkoutAmount(1000, null, 2000), 1000);
  assert.equal(checkoutAmount(null, null, 2000), 2000);
  assert.equal(checkoutAmount(0, null, 2000), 0);
  assert.equal(checkoutAmount(null, { amount: 1000 }, 2000), 1000);
});

test('downgrade classification does not depend on catalogue display order or equal channel counts', () => {
  assert.equal(planChangeKind({ code: 'pro' }, { code: 'scale' }), 'downgrade');
  assert.equal(planChangeKind({ code: 'starter' }, { code: 'demo' }), 'downgrade');
  assert.equal(planChangeKind({ code: 'scale' }, { code: 'pro' }), 'upgrade');
  assert.equal(planChangeKind(null, { code: 'growth' }), 'new');
});
test('rejected request is not displayed as activated', () => {
  assert.notEqual(checkoutRequestLabel('cancelled'), checkoutRequestLabel('active'));
  assert.match(checkoutRequestLabel('cancelled'), /hủy/);
});

test('paid plans show payment before admin review', () => {
  assert.match(checkoutRequestLabel('awaiting_payment'), /thanh toán/);
  assert.match(checkoutRequestLabel('pending'), /admin duyệt/);
});
