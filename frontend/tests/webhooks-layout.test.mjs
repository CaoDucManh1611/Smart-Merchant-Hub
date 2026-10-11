import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const source = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8');
test('webhook redesign preserves status refresh and connection navigation', () => {
  const start = source.indexOf('<section v-if="currentTab === \'webhooks\'"');
  const view = source.slice(start, source.indexOf('</section>', start));
  assert.match(view, /@click="refreshWebhookStatus"/);
  assert.match(view, /:disabled="botConnectionLoading \|\| metaLoading"/);
  assert.match(view, /@click="openChannels"/);
  assert.match(view, /connection.webhook_status === 'connected'/);
  assert.match(view, /metaStatus.instagram_account_id/);
  assert.match(view, /class="webhook-heading-icon" aria-hidden="true"/);
});
test('webhook typography and responsive cards have a reduced-motion alternative', () => {
  assert.match(source, /\.webhooks-layout \.webhook-item strong \{ font-size: 18px;/);
  assert.match(source, /\.webhooks-layout \.webhook-item small \{ font-size: 14px;/);
  assert.match(source, /@media \(max-width: 760px\) \{ \.webhooks-layout \.webhook-checklist \{ grid-template-columns: 1fr;/);
  assert.match(source, /@media \(prefers-reduced-motion: reduce\) \{ \.webhooks-layout \.webhook-card:first-child, \.webhook-refresh \.is-refreshing \{ animation: none;/);
});
