import assert from "node:assert/strict";
import test from "node:test";

import { conversationBotStatus, timelineActor } from "../src/timeline-utils.js";

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

test("conversationBotStatus makes chatbot takeover state clear in Customer 360", () => {
  assert.deepEqual(conversationBotStatus("auto"), {
    kind: "bot",
    label: "Bot đang xử lý",
    description: "Chatbot đang phản hồi tự động cho hội thoại này.",
  });
  assert.deepEqual(conversationBotStatus("human"), {
    kind: "human",
    label: "Nhân viên đang tiếp quản",
    description: "Chatbot đang tạm dừng để nhân viên xử lý hội thoại này.",
  });
});
