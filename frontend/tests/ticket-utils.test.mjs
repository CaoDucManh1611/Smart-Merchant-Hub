import test from "node:test";
import assert from "node:assert/strict";
import { filterConversationsForCustomer } from "../src/ticket-utils.js";

test("filters ticket conversations to the selected customer", () => {
  const conversations = [
    { conversation_id: 3, customer_id: 7, channel: "telegram" },
    { conversation_id: 4, customer_id: 8, channel: "instagram" },
  ];

  assert.deepEqual(
    filterConversationsForCustomer(conversations, "7"),
    [conversations[0]],
  );
});

test("returns no conversations when no customer is selected", () => {
  assert.deepEqual(
    filterConversationsForCustomer([{ conversation_id: 3, customer_id: 7 }], ""),
    [],
  );
});
