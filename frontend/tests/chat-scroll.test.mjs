import test from "node:test";
import assert from "node:assert/strict";
import {
  captureMessageScrollPosition,
  restoreMessageScrollPosition,
  scrollMessageContainerToLatest,
} from "../src/chat-scroll.js";

function message(id, top, bottom = top + 24) {
  return {
    getAttribute: (name) => name === "data-message-id" ? id : null,
    getBoundingClientRect: () => ({ top, bottom }),
  };
}

function container({ top = 100, scrollTop = 0, clientHeight = 400, scrollHeight = 1000, rows = [] } = {}) {
  return {
    scrollTop,
    clientHeight,
    scrollHeight,
    getBoundingClientRect: () => ({ top }),
    querySelectorAll: () => rows,
  };
}

test("chat refresh follows the newest message when the user was at the latest message", () => {
  const view = container({ scrollTop: 600 });
  const position = captureMessageScrollPosition(view);
  assert.equal(position.atLatest, true);

  view.scrollHeight = 1300;
  restoreMessageScrollPosition(view, position);
  assert.equal(view.scrollTop, 1300);
  scrollMessageContainerToLatest(view);
  assert.equal(view.scrollTop, 1300);
});

test("chat refresh preserves the visible message while the user reads older messages", () => {
  const current = message("current", 90, 125);
  const view = container({ top: 100, scrollTop: 220, scrollHeight: 1500, rows: [current] });
  const position = captureMessageScrollPosition(view);
  assert.equal(position.atLatest, false);
  assert.equal(position.messageId, "current");
  assert.equal(position.offset, -10);

  const moved = message("current", 145, 180);
  view.querySelectorAll = () => [moved];
  restoreMessageScrollPosition(view, position);
  assert.equal(view.scrollTop, 275);
});
