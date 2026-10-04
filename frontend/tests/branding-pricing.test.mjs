import assert from 'node:assert/strict';
import fs from 'node:fs';
import test from 'node:test';
const source = name => fs.readFileSync(new URL('../src/' + name, import.meta.url), 'utf8');
test('shared branding uses approved artwork in application and public landing', () => {
  assert.match(source('BrandLogo.vue'), /\/brand\/logo-mark\.svg/);
  assert.match(source('BrandLogo.vue'), /\/brand\/logo-full\.svg/);
  assert.match(source('App.vue'), /<BrandLogo icon \/>/);
  assert.match(source('MarketingLanding.vue'), /<BrandLogo \/>/);
  assert.doesNotMatch(source('App.vue'), />SM<\/span>/);
});
test('pricing uses the current catalogue and existing selection handlers', () => {
  assert.match(source('App.vue'), /<ServicePricing :plans="activeServicePlans"/);
  assert.match(source('App.vue'), /@select="selectServicePlan"/);
  assert.match(source('ServicePricing.vue'), /plan\.price/);
  assert.match(source('ServicePricing.vue'), /plan\.max_channels/);
  assert.match(source('ServicePricing.vue'), /:aria-pressed=/);
  assert.match(source('ServicePricing.vue'), /@media\(max-width:600px\)/);
});
