export const MAX_SAVED_INBOX_VIEWS = 12;

export function normalizeInboxViewFilters(filters = {}) {
  const source = filters && typeof filters === "object" ? filters : {};
  const quickFilter = ["all", "unread", "important"].includes(source.quickFilter)
    ? source.quickFilter
    : "all";

  return {
    search: String(source.search || "").slice(0, 200),
    channel: String(source.channel || "all").slice(0, 80),
    quickFilter,
    phone: String(source.phone || "").slice(0, 60),
    email: String(source.email || "").slice(0, 160),
    tags: Array.isArray(source.tags)
      ? [...new Set(source.tags.map((tag) => String(tag).trim()).filter(Boolean))].slice(0, 40)
      : [],
    tagFilterMode: source.tagFilterMode === "any" ? "any" : "all",
    segmentId: /^\d+$/.test(String(source.segmentId || "")) ? String(source.segmentId) : "",
  };
}

export function normalizeSavedInboxViews(value) {
  if (!Array.isArray(value)) return [];
  const seenIds = new Set();

  return value.flatMap((view) => {
    if (!view || typeof view !== "object") return [];
    const id = String(view.id || "").slice(0, 80);
    const name = String(view.name || "").trim().slice(0, 48);
    if (!id || !name || seenIds.has(id)) return [];
    seenIds.add(id);
    return [{ id, name, filters: normalizeInboxViewFilters(view.filters) }];
  }).slice(0, MAX_SAVED_INBOX_VIEWS);
}
