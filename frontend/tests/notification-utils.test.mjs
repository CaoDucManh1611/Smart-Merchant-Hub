import assert from "node:assert/strict";
import test from "node:test";

import { notificationDestination, unreadNotificationCount } from "../src/notification-utils.js";

test("unreadNotificationCount ignores notifications the staff member has already read", () => {
  assert.equal(unreadNotificationCount([
    { id: 1, is_read: false },
    { id: 2, is_read: true },
    { id: 3, is_read: false },
  ]), 2);
});

test("notificationDestination sends a chatbot draft notification to Sales Orders", () => {
  assert.deepEqual(notificationDestination({
    kind: "chatbot_order_draft",
    metadata: { order_id: 42, conversation_id: 9 },
  }), {
    tab: "orders",
    orderId: 42,
    conversationId: 9,
  });
});

test("notificationDestination sends a CSAT response to its conversation", () => {
  assert.deepEqual(notificationDestination({
    kind: "csat_response",
    metadata: { conversation_id: 9 },
  }), {
    tab: "inbox",
    orderId: null,
    conversationId: 9,
  });
});
