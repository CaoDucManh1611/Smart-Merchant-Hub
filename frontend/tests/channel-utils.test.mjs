import test from "node:test";
import assert from "node:assert/strict";
import { channelLabel } from "../src/channel-utils.js";

test("labels Telegram conversations as Telegram", () => {
  assert.equal(channelLabel("telegram"), "Telegram");
});

test("does not fall back to Facebook for unknown channels", () => {
  assert.equal(channelLabel("zalo"), "ZALO");
});
