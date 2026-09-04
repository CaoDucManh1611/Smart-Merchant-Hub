export function customerTagNames(profile) {
  if (!profile || !Array.isArray(profile.tags)) return [];
  return profile.tags
    .filter((tag) => typeof tag === "string" && tag.trim())
    .map((tag) => tag.trim());
}

export function conversationCustomerTags(conversation) {
  if (!conversation || !Array.isArray(conversation.customer_tags)) return [];
  return conversation.customer_tags
    .filter((tag) => typeof tag === "string" && tag.trim())
    .map((tag) => tag.trim());
}

export function matchesCustomerTagFilter(conversation, tagId, tagName) {
  if (!tagId && !tagName) return true;
  const tags = conversationCustomerTags(conversation);
  return Boolean(tagName && tags.includes(tagName));
}
