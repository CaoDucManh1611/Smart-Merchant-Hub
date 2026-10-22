import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
const source = fs.readFileSync(new URL('../src/MarketingStory.vue', import.meta.url), 'utf8');
test('story auto rotation is guarded and resources are cleaned up', () => {
  for (const guard of ['!props.paused', '!focused.value', 'visible.value', '!document.hidden', '!preference.matches']) assert.ok(source.includes(guard));
  assert.doesNotMatch(source, /stopped|smh-story-pause/);
  assert.match(source, /clearInterval\(timer\)/);
  assert.match(source, /observer\?\.disconnect/);
  assert.match(source, /}, 7000\)/);
});
test('manual selection preserves auto rotation and all six logos are local vectors', () => {
  assert.doesNotMatch(source, /function select\(next\).*stopped.value = true/);
  assert.match(source, /:aria-current=/);
  for (const slug of ['facebook', 'instagram', 'telegram', 'zalo', 'tiktok', 'shopee']) {
    const svg = fs.readFileSync(new URL('../public/brand/platforms/' + slug + '.svg', import.meta.url), 'utf8');
    assert.match(svg, /<path/);
    assert.doesNotMatch(svg, /<script|onload=|<foreignObject/);
  }
});
test('story illustrations keep readable contrast on their light surfaces', () => {
  assert.match(source, /\.smh-story-illustration \{ color:#243b3a; \}/);
  assert.match(source, /\.smh-story-document \{ color:#263c3a; font-size:16px; \}/);
  assert.match(source, /\.smh-story-customer h3 \{ color:#263c3a; font-size:19px; \}/);
  assert.match(source, /\.smh-story-history \{ color:#29433f; font-size:16px; \}/);
});
