export const CHANNEL_LABELS = {
  facebook: "Facebook",
  instagram: "Instagram",
  telegram: "Telegram",
};

export function channelLabel(channel) {
  const normalized = String(channel || "").toLowerCase();
  return CHANNEL_LABELS[normalized] || (normalized ? normalized.toUpperCase() : "Kênh khác");
}
