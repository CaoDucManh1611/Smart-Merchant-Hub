export const CHANNEL_LABELS = {
  facebook: "Facebook",
  instagram: "Instagram",
  telegram: "Telegram",
  // Keep the provider's official uppercase name for internal matching and tests.
  // User-facing views can apply sentence-case styling where needed.
  zalo: "ZALO",
};

export function channelLabel(channel) {
  const normalized = String(channel || "").toLowerCase();
  return CHANNEL_LABELS[normalized] || (normalized ? normalized.toUpperCase() : "Kênh khác");
}
