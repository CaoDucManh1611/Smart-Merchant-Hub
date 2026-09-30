export function unreadNotificationCount(items = []) {
  return items.filter((item) => !item.is_read).length;
}

export const CRITICAL_CONVERSATION_NOTIFICATION_KINDS = new Set([
  "customer_order_confirmation",
  "rag_handoff_required",
]);

export function criticalConversationNotificationCounts(items = []) {
  return items.reduce((counts, notification) => {
    const conversationId = Number(notification?.metadata?.conversation_id);
    if (
      notification?.is_read
      || !conversationId
      || !CRITICAL_CONVERSATION_NOTIFICATION_KINDS.has(notification?.kind)
    ) return counts;
    counts[conversationId] = (counts[conversationId] || 0) + 1;
    return counts;
  }, {});
}

export function notificationDestination(notification = {}) {
  const metadata = notification.metadata || {};
  if (notification.kind === "appointment_reminder" && metadata.appointment_id) {
    return { tab: "appointments", appointmentId: Number(metadata.appointment_id) };
  }
  if (notification.kind === "new_message" && metadata.conversation_id) {
    return {
      tab: "inbox",
      orderId: null,
      conversationId: Number(metadata.conversation_id),
    };
  }
  if (["chatbot_order_draft", "customer_order_confirmation"].includes(notification.kind) && metadata.order_id) {
    return {
      tab: "orders",
      orderId: Number(metadata.order_id),
      conversationId: metadata.conversation_id ? Number(metadata.conversation_id) : null,
    };
  }
  if (notification.kind === "rag_handoff_required" && metadata.conversation_id) {
    return {
      tab: "inbox",
      orderId: null,
      conversationId: Number(metadata.conversation_id),
    };
  }
  if (notification.kind === "csat_response" && metadata.conversation_id) {
    return {
      tab: "inbox",
      orderId: null,
      conversationId: Number(metadata.conversation_id),
    };
  }
  return {
    tab: "tickets",
    orderId: null,
    conversationId: metadata.conversation_id ? Number(metadata.conversation_id) : null,
  };
}
