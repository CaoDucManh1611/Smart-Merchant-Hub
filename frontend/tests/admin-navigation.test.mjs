import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';
import * as Vue from 'vue';
import { parse, compileScript, compileTemplate } from '@vue/compiler-sfc';

test('registration date uses Vietnam timezone and does not invent missing dates', async () => {
  const { subscriptionRegistrationDate } = await import('../src/admin-navigation.js');
  assert.equal(subscriptionRegistrationDate(null), 'Chưa đăng ký');
  assert.equal(subscriptionRegistrationDate('bad'), '—');
  const date = subscriptionRegistrationDate('2026-10-11T18:30:00');
  assert.match(date, /12\/10\/2026/);
  assert.match(date, /01:30/);
  assert.equal(date, subscriptionRegistrationDate('2026-10-11T18:30:00Z'));
});

test('shop list puts newly assigned IDs first without mutating fetched records', async () => {
  const { newestShopsFirst } = await import('../src/admin-navigation.js');
  const shops = [{id:2}, {id:6}, {id:1}, {id:5}];
  assert.deepEqual(newestShopsFirst(shops).map(shop => shop.id), [6,5,2,1]);
  assert.deepEqual(shops.map(shop => shop.id), [2,6,1,5]);
  assert.deepEqual(newestShopsFirst([]), []);
});

test('sidebar illustration is decorative, uses local branding and respects reduced motion', () => {
  const source = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8');
  const css = readFileSync(new URL('../src/admin-design.css', import.meta.url), 'utf8');
  assert.match(source, /class="admin-sidebar-art" aria-hidden="true"/);
  assert.match(source, /src="\/brand\/logo-mark.svg" alt="" class="admin-art-brand"/);
  assert.match(css, /@media\(prefers-reduced-motion:no-preference\)/);
  assert.match(css, /@media\(prefers-reduced-motion:reduce\)/);
  assert.match(css, /\.admin-sidebar-art \{ display:none; \}/);
  assert.doesNotMatch(css, /animation:[^;]*infinite/);
});

test('shared section heading precedes both columns and sidebar scrolling is viewport bounded', () => {
  const source = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8');
  const css = readFileSync(new URL('../src/admin-design.css', import.meta.url), 'utf8');
  assert.ok(source.indexOf('ref="adminSectionHeading"') < source.indexOf('class="admin-workspace-body"'));
  assert.match(css, /max-height:calc\(100dvh - 40px\)/);
  assert.match(css, /max-height:none; overflow:visible/);
});

test('admin navigation includes support and preserves legacy hashes', async () => {
  const { ADMIN_SECTIONS, adminSectionFromHash, adminSectionHash } = await import('../src/admin-navigation.js');
  assert.deepEqual(ADMIN_SECTIONS.map(section => section.id), ['team', 'knowledge', 'support', 'overview', 'approvals', 'shops', 'plans', 'isolation', 'health', 'otp-email', 'audit', 'payments', 'backups']);
  for (const section of ADMIN_SECTIONS) {
    assert.equal(adminSectionFromHash(`#admin-${section.id}`), section.id);
    assert.equal(adminSectionHash(section.id), `#admin-${section.id}`);
    assert.ok(section.title && section.description && section.icon);
  }
  for (const hash of ['', '#unknown', '#admin-__proto__', '#admin-shops/other', null, undefined]) assert.equal(adminSectionFromHash(hash), 'overview');
  assert.equal(adminSectionHash('unknown'), '#admin-overview');
});

test('admin panels remain mounted and navigation exposes history, focus and mobile semantics', () => {
  const source = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8');
  for (const id of ['overview', 'approvals', 'shops', 'plans', 'isolation', 'health', 'otp-email', 'audit', 'payments']) assert.ok(source.includes(`v-show="activePlatformSection === '${id}'"`), id);
  assert.match(source, /<PlatformOtpEmail[^>]*v-show=/);
  assert.match(source, /id="admin-menu-navigation"/);
  assert.match(source, /aria-controls="admin-menu-navigation"/);
  assert.match(source, /:aria-expanded="adminMenuOpen"/);
  assert.match(source, /:aria-current="activePlatformSection === section.id \? 'page' : undefined"/);
  assert.match(source, /addEventListener\("hashchange", syncPlatformSectionFromHash\)/);
  assert.match(source, /removeEventListener\("hashchange", syncPlatformSectionFromHash\)/);
  assert.match(source, /ref="adminSectionHeading" tabindex="-1"/);
  assert.match(source, /adminSectionHeading.value\?\.focus/);
  assert.match(source, /watch\(inPlatformAdminWorkspace/);
  assert.match(source, /class="admin-section-stack"/);
});

test('hash changes restore selection, close mobile menu and focus heading', async () => {
  const helpers = await import('../src/admin-navigation.js');
  const source = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8');
  const start = source.indexOf('const activePlatformSection =');
  const end = source.indexOf('const platformShopDetails =', start);
  let workspaceWatcher;
  let focusCount = 0;
  const context = vm.createContext({ ...helpers, ref: Vue.ref, computed: Vue.computed, nextTick: Vue.nextTick,
    watch: (_, callback) => { workspaceWatcher = callback; }, inPlatformAdminWorkspace: { value: true }, visibleAdminSections: { value: helpers.ADMIN_SECTIONS },
    window: { location: { hash: '#admin-otp-email' } },
  });
  vm.runInContext(source.slice(start, end) + '\nglobalThis.navigation = {activePlatformSection,adminMenuOpen,adminSectionHeading,selectPlatformSection,syncPlatformSectionFromHash};', context);
  const nav = context.navigation;
  nav.adminSectionHeading.value = { focus: () => { focusCount++; } };
  assert.equal(nav.activePlatformSection.value, 'otp-email');
  nav.adminMenuOpen.value = true;
  nav.selectPlatformSection('plans');
  assert.equal(context.window.location.hash, '#admin-plans');
  await nav.syncPlatformSectionFromHash();
  assert.equal(nav.activePlatformSection.value, 'plans');
  assert.equal(nav.adminMenuOpen.value, false);
  context.window.location.hash = '#admin-otp-email';
  await nav.syncPlatformSectionFromHash();
  assert.equal(nav.activePlatformSection.value, 'otp-email');
  assert.equal(focusCount, 2);
  context.inPlatformAdminWorkspace.value = false;
  context.window.location.hash = '#admin-audit';
  await nav.syncPlatformSectionFromHash();
  assert.equal(nav.activePlatformSection.value, 'otp-email');
  context.inPlatformAdminWorkspace.value = true;
  workspaceWatcher(true); await Vue.nextTick();
  assert.equal(nav.activePlatformSection.value, 'audit');
});

test('App navigation template compiles and panel visibility uses v-show rather than remounting', () => {
  const source = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8');
  const { descriptor, errors } = parse(source);
  assert.deepEqual(errors, []);
  const script = compileScript(descriptor, { id: 'admin-navigation-test' });
  const template = compileTemplate({ source: descriptor.template.content, filename: 'App.vue', id: 'admin-navigation-test', compilerOptions: { bindingMetadata: script.bindings } });
  assert.deepEqual(template.errors, []);
  const admin = source.slice(source.indexOf('PLATFORM ADMINISTRATION (CONTROL PLANE)'), source.indexOf('SẢN PHẨM (PRODUCT CATALOG)'));
  assert.doesNotMatch(admin, /v-if="activePlatformSection/);
  assert.equal((admin.match(/class="admin-section-content"/g) || []).length, 1);
  assert.equal((admin.match(/class="products-header platform-admin-hero"/g) || []).length, 1);
});
