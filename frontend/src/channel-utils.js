import { t } from "./i18n.js";

export const CHANNEL_LABELS = {
  facebook: "Facebook",
  instagram: "Instagram",
  telegram: "Telegram",
  zalo: "Zalo",
  tiktok: "TikTok",
  shopee: "Shopee",
};

export function channelLabel(channel) {
  const normalized = String(channel || "").toLowerCase();
  return CHANNEL_LABELS[normalized] || (normalized ? normalized.charAt(0).toUpperCase() + normalized.slice(1) : t("Kênh khác"));
}
