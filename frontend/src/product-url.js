export function safeProductUrl(value) {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  if (!trimmed || trimmed.length > 2048 || /\s/.test(trimmed)) return null;
  try {
    const parsed = new URL(trimmed);
    if (!["http:", "https:"].includes(parsed.protocol) || !parsed.hostname || parsed.username || parsed.password) return null;
    return trimmed;
  } catch {
    return null;
  }
}
