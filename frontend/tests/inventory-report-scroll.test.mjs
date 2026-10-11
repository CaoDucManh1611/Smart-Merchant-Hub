import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

test('inventory report keeps every product in a keyboard-accessible ten-row scroll area', () => {
  const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8');
  const css = readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');
  assert.match(app, /class="products-table-wrap inventory-report-scroll" role="region" aria-label="Tồn kho" tabindex="0"/);
  assert.match(app, /v-for="item in inventoryReport.items"/);
  assert.match(css, /\.inventory-report-scroll \{ max-height: 568px; overflow: auto;/);
  assert.match(css, /\.inventory-report-scroll \.products-table td \{[^}]*height: 52px;/);
  assert.match(css, /\.inventory-report-scroll \.products-table th \{[^}]*height: 48px;[^}]*position: sticky; top: 0;/);
  assert.equal(48 + 10 * 52, 568);
});
