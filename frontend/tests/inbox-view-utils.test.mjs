import assert from "node:assert/strict";
import test from "node:test";
import { MAX_SAVED_INBOX_VIEWS, normalizeSavedInboxViews } from "../src/inbox-view-utils.js";

test("saved inbox views are bounded and malformed filters fall back safely", () => {
  const views = normalizeSavedInboxViews([
    null,
    { id: "one", name: "Unread", filters: { quickFilter: "unread", tags: ["vip", "vip"], segmentId: "../bad" } },
    { id: "one", name: "Duplicate id" },
    ...Array.from({ length: MAX_SAVED_INBOX_VIEWS + 2 }, (_, index) => ({ id: `view-${index}`, name: `View ${index}` })),
  ]);

  assert.equal(views.length, MAX_SAVED_INBOX_VIEWS);
  assert.deepEqual(views[0].filters.tags, ["vip"]);
  assert.equal(views[0].filters.segmentId, "");
  assert.equal(views[0].filters.quickFilter, "unread");
});
