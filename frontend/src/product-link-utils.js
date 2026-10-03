export function normalizeProductUrl(value) {
  const text = String(value || "").trim();
  if (!text) return "";

  let url;
  try {
    url = new URL(text);
  } catch {
    return null;
  }

  if (!['http:', 'https:'].includes(url.protocol) || !url.hostname || url.username || url.password) {
    return null;
  }
  return url.href;
}