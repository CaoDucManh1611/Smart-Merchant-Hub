import assert from "node:assert/strict";
import test from "node:test";
import { workQueueItems } from "../src/work-queue-utils.js";

test("work queue uses live record statuses and due dates", () => {
  const now = new Date("2026-09-28T12:00:00Z");
  const result = workQueueItems({
    tickets: [
      { id: 1, status: "open", sla_due_at: "2026-09-28T11:00:00Z" },
      { id: 2, status: "closed", sla_due_at: "2026-09-27T11:00:00Z" },
    ],
    conversations: [
      { conversation_id: 3, status: "open", assigned_user_id: null },
      { conversation_id: 4, status: "open", assigned_user_id: 12 },
    ],
    appointments: [
      { id: 5, status: "scheduled", starts_at: "2026-09-29T12:00:00Z" },
      { id: 6, status: "scheduled", starts_at: "2026-10-10T12:00:00Z" },
    ],
    quotes: [{ id: 7, status: "sent" }, { id: 8, status: "accepted" }],
    documents: [{ id: 9, status: "processing" }, { id: 10, status: "failed" }],
    runs: { 9: { status: "failed" } },
  }, now);
  assert.deepEqual(Object.values(result).map((items) => items.map((item) => item.id)), [[1], [3], [5], [7], [9, 10]]);
});

test("missing deadlines and completed records never become urgent work", () => {
  const result = workQueueItems({
    tickets: [{ id: 1, status: "pending", sla_due_at: null }],
    appointments: [{ id: 2, status: "completed", starts_at: "2026-09-29T12:00:00Z" }],
    documents: [{ id: 3, status: "ready" }],
  }, new Date("2026-09-28T12:00:00Z"));
  assert.deepEqual(Object.values(result).map((items) => items.length), [0, 0, 0, 0, 0]);
});
