import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

test('inventory report starts compact and reveals more rows on demand', () => {
  const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8');
  const css = readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');
  assert.match(app, /class="products-table-wrap inventory-report-scroll" role="region" aria-label="Tồn kho" tabindex="0"/);
  assert.match(app, /v-for="item in inventoryReport.items\.slice\(0, inventoryReportVisibleCount\)"/);
  assert.match(app, /inventoryReportVisibleCount \+= 5/);
  assert.match(app, /inventoryReportVisibleCount = 5/);
  assert.match(css, /\.inventory-report-scroll \{ max-height: none; overflow-x: auto; overflow-y: visible;/);
  assert.match(css, /\.inventory-report-scroll \.products-table td \{[^}]*height: 52px;/);
  assert.match(css, /\.inventory-report-scroll \.products-table th \{[^}]*height: 48px;/);
});
