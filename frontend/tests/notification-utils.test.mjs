import assert from "node:assert/strict";
import test from "node:test";

import { criticalConversationNotificationCounts, notificationDestination, unreadNotificationCount } from "../src/notification-utils.js";

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

test("notificationDestination sends a customer-confirmed invoice to Sales Orders", () => {
  assert.deepEqual(notificationDestination({
    kind: "customer_order_confirmation",
    metadata: { order_id: 42, conversation_id: 9 },
  }), {
    tab: "orders",
    orderId: 42,
    conversationId: 9,
  });
});

test("critical conversation badges include only unread order approvals and AI handoffs", () => {
  assert.deepEqual(criticalConversationNotificationCounts([
    { kind: "new_message", is_read: false, metadata: { conversation_id: 3 } },
    { kind: "customer_order_confirmation", is_read: false, metadata: { conversation_id: 3 } },
    { kind: "rag_handoff_required", is_read: false, metadata: { conversation_id: 3 } },
    { kind: "rag_handoff_required", is_read: true, metadata: { conversation_id: 4 } },
  ]), { 3: 2 });
});

test("notificationDestination opens the inbox for an AI handoff", () => {
  assert.deepEqual(notificationDestination({
    kind: "rag_handoff_required",
    metadata: { conversation_id: 9 },
  }), {
    tab: "inbox",
    orderId: null,
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

test("notificationDestination sends a new customer message to its conversation", () => {
  assert.deepEqual(notificationDestination({
    kind: "new_message",
    metadata: { conversation_id: 19 },
  }), {
    tab: "inbox",
    orderId: null,
    conversationId: 19,
  });
});

test("notificationDestination opens the appointment schedule for a reminder", () => {
  assert.deepEqual(notificationDestination({
    kind: "appointment_reminder",
    metadata: { appointment_id: "31" },
  }), { tab: "appointments", appointmentId: 31 });
});
