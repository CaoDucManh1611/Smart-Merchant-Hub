import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { outboundMediaAccept, outboundMediaTypes, supportsOutboundMedia } from "../src/media-capabilities.js";

const appVue = fs.readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");

test("media picker exposes only attachments supported by the selected channel", () => {
  assert.deepEqual(outboundMediaTypes("facebook"), ["image", "audio", "video", "file"]);
  assert.deepEqual(outboundMediaTypes("instagram"), ["image", "audio", "video", "file"]);
  assert.deepEqual(outboundMediaTypes("telegram"), ["image", "audio", "video", "file", "sticker"]);
  assert.deepEqual(outboundMediaTypes("zalo", "bot"), ["image", "audio", "sticker"]);
  assert.deepEqual(outboundMediaTypes("zalo", "oa"), ["image"]);
  assert.deepEqual(outboundMediaTypes("tiktok"), []);
  assert.deepEqual(outboundMediaTypes("shopee"), []);
  assert.equal(supportsOutboundMedia("zalo", "audio", "oa"), false);
  assert.equal(supportsOutboundMedia("telegram", "audio"), true);
  assert.match(outboundMediaAccept("zalo", "oa"), /image\/jpeg/);
  assert.doesNotMatch(outboundMediaAccept("zalo", "oa"), /audio/);
});

test("composer applies capability-specific picker and voice controls", () => {
  assert.match(appVue, /:accept="selectedOutboundMediaAccept"/);
  assert.match(appVue, /!selectedSupportsOutboundMedia/);
  assert.match(appVue, /!selectedSupportsVoice/);
  assert.match(appVue, /formData\.append\("is_voice_note", "true"\)/);
});
