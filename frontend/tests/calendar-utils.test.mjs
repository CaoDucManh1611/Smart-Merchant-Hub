import assert from "node:assert/strict";
import test from "node:test";

import { appointmentsToIcs } from "../src/calendar-utils.js";

test("calendar export emits escaped, stable appointment events and skips malformed rows", () => {
  const calendar = appointmentsToIcs([
    {
      id: 7,
      service_name: "Tư vấn; gói, A",
      customer_name: "Khách\nVIP",
      starts_at: "2026-10-01T01:00:00Z",
      ends_at: "2026-10-01T02:00:00Z",
      status: "scheduled",
      notes: "Mang hồ sơ,\nđến sớm",
    },
    { id: 8, status: "cancelled", starts_at: "2026-10-02T01:00:00Z", ends_at: "2026-10-02T02:00:00Z" },
    { id: 9, starts_at: "bad" },
  ], new Date("2026-09-26T00:00:00Z"));

  assert.match(calendar, /BEGIN:VCALENDAR\r\n/);
  assert.match(calendar, /UID:appointment-7@smart-merchant-hub/);
  assert.match(calendar, /SUMMARY:Tư vấn\\; gói\\, A - Khách\\nVIP/);
  assert.match(calendar, /DESCRIPTION:Mang hồ sơ\\,\\nđến sớm/);
  assert.match(calendar, /STATUS:CANCELLED/);
  assert.equal((calendar.match(/BEGIN:VEVENT/g) || []).length, 2);
});
