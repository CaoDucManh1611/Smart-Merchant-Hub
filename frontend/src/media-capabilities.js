const CHANNEL_MEDIA_TYPES = {
  facebook: ["image", "audio", "video", "file"],
  instagram: ["image", "audio", "video", "file"],
  telegram: ["image", "audio", "video", "file", "sticker"],
  tiktok: [],
  shopee: [],
};

const MEDIA_ACCEPT = {
  image: "image/jpeg,image/png,image/webp,image/gif",
  audio: "audio/*",
  video: "video/*",
  sticker: "image/webp,image/png,image/jpeg",
  file: ".pdf,.zip,.rar,.7z,.csv,.txt,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.rtf",
};

export function outboundMediaTypes(channel, provider = "") {
  const normalizedChannel = String(channel || "").trim().toLowerCase();
  if (normalizedChannel !== "zalo") return CHANNEL_MEDIA_TYPES[normalizedChannel] || [];
  const normalizedProvider = String(provider || "bot").trim().toLowerCase();
  return ["oa", "zalo_oa", "official_account"].includes(normalizedProvider)
    ? ["image"]
    : ["image", "audio", "sticker"];
}

export function outboundMediaAccept(channel, provider = "") {
  return [...new Set(outboundMediaTypes(channel, provider).flatMap((type) => MEDIA_ACCEPT[type] || []))].join(",");
}

export function supportsOutboundMedia(channel, mediaType, provider = "") {
  return outboundMediaTypes(channel, provider).includes(String(mediaType || "").trim().toLowerCase());
}
