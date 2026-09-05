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

export function matchesCustomerTagFilter(conversation, selectedTags, matchMode = "all") {
  // Keep compatibility with the former (tagId, tagName) signature while
  // allowing the inbox to filter by multiple customer tags.
  if (typeof matchMode === "string" && !["all", "any"].includes(matchMode)) {
    selectedTags = matchMode ? [matchMode] : [];
    matchMode = "all";
  }
  const wanted = (Array.isArray(selectedTags) ? selectedTags : [selectedTags])
    .filter((tag) => typeof tag === "string" && tag.trim())
    .map((tag) => tag.trim());
  if (!wanted.length) return true;
  const tags = conversationCustomerTags(conversation);
  return matchMode === "any"
    ? wanted.some((tag) => tags.includes(tag))
    : wanted.every((tag) => tags.includes(tag));
}
