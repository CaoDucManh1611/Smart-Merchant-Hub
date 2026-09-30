const ABSOLUTE_MEDIA_URL = /^(?:https?:|blob:|data:|file:)/i;

/**
 * Resolve attachment URLs returned by the API for use in the browser.
 *
 * The backend intentionally returns tenant-safe relative URLs such as
 * `/api/media/42`. The SPA is served from port 5173 while the API is served
 * from port 8000, so handing that path directly to an img/audio/video tag
 * makes the browser request the frontend origin and produces a blank player.
 */
export function resolveMediaUrl(value, apiBase = "") {
  const raw = String(value ?? "").trim();
  if (!raw || ABSOLUTE_MEDIA_URL.test(raw)) {
    return raw;
  }

  const normalizedBase = String(apiBase ?? "").trim().replace(/\/+$/, "");
  const apiOrigin = normalizedBase.endsWith("/api")
    ? normalizedBase.slice(0, -4)
    : normalizedBase;

  if (raw.startsWith("//")) {
    return raw;
  }

  if (raw.startsWith("/")) {
    return apiOrigin ? `${apiOrigin}${raw}` : raw;
  }

  return normalizedBase ? `${normalizedBase}/${raw}` : raw;
}

export function displayAttachments(message, apiBase = "") {
  const supplied = Array.isArray(message?.attachments)
    ? message.attachments
    : [];

  if (supplied.length) {
    return supplied.map((attachment) => ({
      ...attachment,
      media_type: String(
        attachment?.media_type
        || attachment?.mediaType
        || "file",
      ).trim().toLowerCase(),
      media_url: resolveMediaUrl(
        attachment?.media_url
        || attachment?.url
        || attachment?.source_url
        || "",
        apiBase,
      ),
    }));
  }

  const mediaUrl = resolveMediaUrl(
    message?.media_url || message?.mediaUrl || "",
    apiBase,
  );
  if (!mediaUrl) {
    return [];
  }

  return [{
    media_type: String(
      message?.media_type || message?.mediaType || "file",
    ).trim().toLowerCase(),
    media_url: mediaUrl,
  }];
}
