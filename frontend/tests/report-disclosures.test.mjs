import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { parse } from '@vue/compiler-sfc';

test('reports show four primary metrics and collapse optional content without dropping reports', () => {
  const source = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8');
  const { descriptor, errors } = parse(source);
  assert.equal(errors.length, 0);
  let reports;
  function walk(node) {
    if (node.type === 1 && node.tag === 'section' && node.props.some(p => p.name === 'class' && p.value?.content.includes('reports-layout'))) reports = node;
    for (const child of node.children || []) walk(child);
  }
  walk(descriptor.template.ast);
  assert.ok(reports);
  const overview = reports.children.find(n => n.type === 1 && n.tag === 'template');
  const cards = overview.children.find(n => n.type === 1 && n.props.some(p => p.name === 'class' && p.value?.content === 'report-cards'));
  assert.equal(cards.children.filter(n => n.type === 1).length, 4);
  const disclosures = [];
  function collect(node) { if (node.tag === 'details') disclosures.push(node); for (const child of node.children || []) collect(child); }
  collect(reports);
  assert.equal(disclosures.length, 7);
  for (const details of disclosures) {
    assert.equal(details.children.find(n => n.type === 1).tag, 'summary');
    assert.ok(!details.props.some(p => p.name === 'open'));
  }
  for (const feature of ['downloadReportCsv', 'openCommerceReportRecord(record)', 'recalculateRevenueAttribution', 'inventory-report-scroll', 'v-for="item in inventoryReport.items.slice(0, inventoryReportVisibleCount)"']) assert.ok(source.includes(feature));
});
