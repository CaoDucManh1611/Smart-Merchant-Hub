import assert from "node:assert/strict";
import test from "node:test";

import { timelineActor } from "../src/timeline-utils.js";

test("timelineActor gives Customer 360 a human-readable owner for each chat message", () => {
  assert.deepEqual(timelineActor({ event_type: "message", actor_type: "customer" }), {
    kind: "customer",
    label: "Khách hàng",
  });
  assert.deepEqual(timelineActor({ event_type: "message", actor_type: "bot" }), {
    kind: "bot",
    label: "Chatbot",
  });
  assert.deepEqual(timelineActor({ event_type: "message", actor_type: "staff", actor_name: "Linh tư vấn" }), {
    kind: "staff",
    label: "Nhân viên · Linh tư vấn",
  });
});
