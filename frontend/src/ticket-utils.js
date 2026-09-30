export function filterConversationsForCustomer(conversations, customerId) {
  const selectedCustomerId = Number(customerId);
  if (!selectedCustomerId || !Array.isArray(conversations)) return [];

  return conversations.filter(
    (conversation) => Number(conversation?.customer_id) === selectedCustomerId,
  );
}
