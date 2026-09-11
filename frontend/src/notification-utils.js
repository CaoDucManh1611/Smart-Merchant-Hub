export function unreadNotificationCount(items = []) {
  return items.filter((item) => !item.is_read).length;
}

export function notificationDestination(notification = {}) {
  const metadata = notification.metadata || {};
  if (notification.kind === "chatbot_order_draft" && metadata.order_id) {
    return {
      tab: "orders",
      orderId: Number(metadata.order_id),
      conversationId: metadata.conversation_id ? Number(metadata.conversation_id) : null,
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
