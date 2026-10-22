import test from "node:test";
import assert from "node:assert/strict";
import { channelLabel } from "../src/channel-utils.js";

test("labels Telegram conversations as Telegram", () => {
  assert.equal(channelLabel("telegram"), "Telegram");
});

test("labels local Shopee connector conversations as Shopee", () => {
  assert.equal(channelLabel("shopee"), "Shopee");
});

test("does not fall back to Facebook for unknown channels", () => {
  assert.equal(channelLabel("unknown-provider"), "Unknown-provider");
});

test("uses the registered Zalo label instead of an unknown-channel fallback", () => {
  assert.equal(channelLabel("zalo"), "Zalo");
});
