import { channelLabel } from "./channel-utils.js";

export const DEFAULT_INBOX_CHANNELS = Object.freeze([
  "facebook",
  "instagram",
  "telegram",
  "zalo",
]);

export function getInboxChannels(conversations = [], supportedChannels = DEFAULT_INBOX_CHANNELS) {
  const counts = new Map();
  for (const conversation of conversations || []) {
    const channel = String(conversation?.channel || "").trim().toLowerCase();
    if (!channel) continue;
    counts.set(channel, (counts.get(channel) || 0) + 1);
  }

  const orderedChannels = [
    ...supportedChannels,
    ...Array.from(counts.keys()).filter((channel) => !supportedChannels.includes(channel)),
  ];

  return orderedChannels.map((channel) => ({
    value: channel,
    label: channelLabel(channel),
    count: counts.get(channel) || 0,
  }));
}
