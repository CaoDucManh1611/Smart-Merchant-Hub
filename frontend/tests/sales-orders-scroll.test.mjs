import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

test('sales orders scroll independently with a sticky header and keyboard access', () => {
  const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8');
  const css = readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');
  assert.equal((app.match(/sales-orders-scroll/g) || []).length, 1);
  assert.match(app, /sales-orders-scroll" role="region" aria-label="Đơn bán" tabindex="0"/);
  assert.match(css, /\.sales-orders-scroll \{[^}]*max-height:[^}]*overflow: auto/);
  assert.match(css, /\.sales-orders-scroll \.orders-table th \{[^}]*position: sticky; top: 0/);
});
