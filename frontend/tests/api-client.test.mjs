import assert from "node:assert/strict";
import test from "node:test";

import { apiFetch, AUTH_EXPIRED_EVENT } from "../src/api-client.js";

test("a 401 clears the expired token and emits one session event", async () => {
  const values = new Map([["crm_access_token", "expired-token"]]);
  const storage = {
    getItem: (key) => values.get(key) || null,
    removeItem: (key) => values.delete(key),
  };
  const browserWindow = new EventTarget();
  browserWindow.localStorage = storage;
  const previousWindow = globalThis.window;
  const previousFetch = globalThis.fetch;
  globalThis.window = browserWindow;
  globalThis.fetch = async () => new Response(null, { status: 401 });
  let events = 0;
  browserWindow.addEventListener(AUTH_EXPIRED_EVENT, () => { events += 1; });
  try {
    await apiFetch("/api/conversations");
    await apiFetch("/api/conversations");
    assert.equal(values.has("crm_access_token"), false);
    assert.equal(events, 1);
  } finally {
    globalThis.window = previousWindow;
    globalThis.fetch = previousFetch;
  }
});
