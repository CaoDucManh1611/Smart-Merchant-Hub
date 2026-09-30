const escapeIcs = (value) => String(value || "")
  .replace(/\\/g, "\\\\")
  .replace(/\r?\n/g, "\\n")
  .replace(/,/g, "\\,")
  .replace(/;/g, "\\;");

const icsDate = (value) => new Date(value).toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");

export function appointmentsToIcs(items, now = new Date()) {
  const lines = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//Smart Merchant Hub//CRM Calendar//VI",
    "CALSCALE:GREGORIAN",
    "METHOD:PUBLISH",
  ];
  for (const item of items || []) {
    if (!item?.id || !item.starts_at || !item.ends_at) continue;
    const startsAt = new Date(item.starts_at);
    const endsAt = new Date(item.ends_at);
    if (Number.isNaN(startsAt.getTime()) || Number.isNaN(endsAt.getTime()) || endsAt <= startsAt) continue;
    const title = [item.service_name, item.customer_name].filter(Boolean).join(" - ") || `Lịch hẹn #${item.id}`;
    lines.push(
      "BEGIN:VEVENT",
      `UID:appointment-${item.id}@smart-merchant-hub`,
      `DTSTAMP:${icsDate(now)}`,
      `DTSTART:${icsDate(startsAt)}`,
      `DTEND:${icsDate(endsAt)}`,
      `SUMMARY:${escapeIcs(title)}`,
      `DESCRIPTION:${escapeIcs(item.notes)}`,
      `STATUS:${item.status === "cancelled" ? "CANCELLED" : "CONFIRMED"}`,
      "END:VEVENT",
    );
  }
  lines.push("END:VCALENDAR", "");
  return lines.join("\r\n");
}
