import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';

const css = fs.readFileSync(new URL('../src/inbox-design.css', import.meta.url), 'utf8');
const main = fs.readFileSync(new URL('../src/main.js', import.meta.url), 'utf8');
const globalCss = fs.readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');
const marketingSource = fs.readFileSync(new URL('../src/MarketingLanding.vue', import.meta.url), 'utf8');
const signupCss = fs.readFileSync(new URL('../src/signup-design.css', import.meta.url), 'utf8');

test('inbox presentation is scoped away from public auth and platform administration', () => {
  assert.match(main, /import "\.\/inbox-design\.css"/);
  const rules = [...css.matchAll(/([^{}]+)\{/g)].map(m => m[1].trim());
  for (const rule of rules.filter(r => !r.startsWith('@') && !r.startsWith('/*') && !r.includes('.ui-language-control'))) {
    assert.match(rule, /\.crm-app:not\(\.platform-admin-workspace\) \.layout/);
  }
  assert.doesNotMatch(css, /pointer-events:\s*none|visibility:\s*hidden/);
  assert.match(css, /:not\(:focus-within\):not\(\.has-composer-content\)/);
});

test('inbox supports dark mode, existing panel collapse, keyboard focus and narrow screens', () => {
  assert.match(css, /body\.crm-dark/);
  assert.match(css, /\.layout\.customer-panel-collapsed/);
  assert.match(css, /:focus-visible/);
  assert.match(css, /max-width: 760px/);
  assert.match(css, /\.chat-head \.chat-tools[\s\S]*?flex-wrap: wrap/);
});

test('expanded customer profile sections use readable form, empty and summary treatments', () => {
  assert.match(css, /\.customer-section-accordion\[open\]/);
  assert.match(css, /\.customer-timeline-filters/);
  assert.match(css, /\.customer-tag-form/);
  assert.match(css, /\.facts-empty, \.tags-empty, \.customer-timeline-placeholder/);
  assert.match(css, /\.customer-timeline-summary/);
});

test('the product uses one Vietnamese-first typeface across CRM, marketing and signup', () => {
  assert.match(globalCss, /family=Be\+Vietnam\+Pro/);
  assert.match(globalCss, /--font-ui:\s*"Be Vietnam Pro"/);
  assert.match(globalCss, /button,[\s\S]*?font-family:\s*var\(--font-ui\)/);
  assert.match(marketingSource, /font-family:var\(--font-ui\)/);
  assert.match(signupCss, /font-family:var\(--font-ui\)/);
});
