import assert from "node:assert/strict";
import test from "node:test";

import { getInboxChannels } from "../src/inbox-utils.js";

test("inbox channel list includes all supported platforms and counts conversations", () => {
  const channels = getInboxChannels([
    { channel: "telegram" },
    { channel: "zalo" },
    { channel: "zalo" },
  ]);

  assert.deepEqual(channels, [
    { value: "facebook", label: "Facebook", count: 0 },
    { value: "instagram", label: "Instagram", count: 0 },
    { value: "telegram", label: "Telegram", count: 1 },
    { value: "zalo", label: "ZALO", count: 2 },
  ]);
});

test("inbox channel list appends an active provider not in the default catalog", () => {
  const channels = getInboxChannels([{ channel: "whatsapp" }]);

  assert.equal(channels.at(-1).value, "whatsapp");
  assert.equal(channels.at(-1).label, "WHATSAPP");
  assert.equal(channels.at(-1).count, 1);
});
