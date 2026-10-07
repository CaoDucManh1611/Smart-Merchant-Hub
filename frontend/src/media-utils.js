const ABSOLUTE_MEDIA_URL = /^(?:https?:|blob:|data:|file:)/i;

export function displayMessageText(value, channel = "", direction = "") {
  let text = String(value ?? "");
  if (["facebook", "instagram"].includes(String(channel).trim().toLowerCase()) && direction === "outbound") {
    text = text.replace(/\s*(?:(?:Đã gửi|Đã xem|Sent|Seen)\s*)?Người gửi\s*:\s*[\s\S]*$/iu, "").trim();
  }
  if (String(channel).trim().toLowerCase() !== "tiktok") {
    return text;
  }
  return text.replace(/^\[Khách gửi nội dung TikTok\]\s*/i, "").trim();
}

export function visibleConversationMessages(messages = [], channel = "") {
  const rows = Array.isArray(messages) ? messages : [];
  if (!["facebook", "instagram"].includes(String(channel).trim().toLowerCase())) return rows;

  const body = (message) => displayMessageText(message?.content, channel, message?.direction)
    .replace(/\s+/g, " ").trim().toLocaleLowerCase();
  return rows.filter((message, messageIndex) => {
    if (message?.direction !== "outbound"
      || message?.sender_type === "bot"
      || message?.raw_payload?.source !== "meta_history_import") return true;

    const echoBody = body(message);
    const echoTime = Date.parse(message?.received_at || "");
    if (!echoBody) return true;

    // Meta history may omit timestamps, but the imported echo is adjacent to
    // the local bot row. Only use adjacency when at least one timestamp is missing.
    return !rows.some((candidate, candidateIndex) => {
      if (candidate === message || candidate?.direction !== "outbound" || candidate?.sender_type !== "bot") return false;
      const botTime = Date.parse(candidate?.received_at || "");
      if (body(candidate) !== echoBody) return false;
      if (Number.isFinite(echoTime) && Number.isFinite(botTime)) {
        return Math.abs(echoTime - botTime) <= 3 * 60 * 1000;
      }
      return Math.abs(messageIndex - candidateIndex) === 1;
    });
  });
}

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
