import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8');
const saveSource = source.slice(source.indexOf('async function saveProduct()'), source.indexOf('\nfunction productStatusLabel'));

test('manual product form keeps file import and shows existing products above fields', () => {
  assert.match(source, /aria-controls="product-manual-panel"/);
  assert.match(source, /@submit.prevent="saveProduct"/);
  assert.match(source, /:disabled="productSaving" class="product-manual-fields"/);
  assert.match(source, /@click.stop="openProductFilePicker"/);
  assert.ok(source.indexOf('class="product-manual-reference"') < source.indexOf('class="product-manual-fields"'));
});

function setup(overrides = {}) {
  const calls = [];
  const context = {
    productForm: { value: { id: null, sku: ' NEW-1 ', name: ' Bình nước ', description: '', product_url: '', price: 125000, stock_quantity: 4, status: 'active', ...overrides } },
    productSaving: { value: false }, productError: { value: '' }, productUploadNotice: { value: '' },
    products: { value: [{ id: 1, sku: 'OLD-1' }] }, API_BASE: '/api',
    safeProductUrl: () => null, t: (s) => s, friendlyErrorMessage: (e) => e.message,
    apiFetch: async (url, options) => { calls.push({ url, ...options }); return { ok: true }; },
    resetProductForm: () => {}, fetchProducts: async () => {},
  };
  vm.createContext(context);
  vm.runInContext(saveSource, context);
  return { context, calls };
}

test('manual product saves trimmed fields and initial stock through existing API', async () => {
  const { context, calls } = setup();
  await context.saveProduct();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].method, 'POST');
  const payload = JSON.parse(calls[0].body);
  assert.equal(payload.sku, 'NEW-1');
  assert.equal(payload.name, 'Bình nước');
  assert.equal(payload.stock_quantity, 4);
  assert.equal(context.productSaving.value, false);
  assert.ok(context.productUploadNotice.value);
});

test('manual product rejects invalid numbers, duplicate SKU and repeated submission', async () => {
  for (const overrides of [{ price: -1 }, { price: '' }, { stock_quantity: 1.5 }, { stock_quantity: -1 }, { sku: 'OLD-1' }, { name: ' ' }]) {
    const { context, calls } = setup(overrides);
    await context.saveProduct();
    assert.equal(calls.length, 0);
    assert.ok(context.productError.value);
  }
  const { context, calls } = setup();
  context.productSaving.value = true;
  await context.saveProduct();
  assert.equal(calls.length, 0);
});
