import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { displayAttachments, displayMessageText, resolveMediaUrl, visibleConversationMessages } from "../src/media-utils.js";

const appVue = fs.readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");
const stylesheet = fs.readFileSync(new URL("../src/style.css", import.meta.url), "utf8");

test("resolves backend-relative media URLs against the API origin", () => {
  assert.equal(
    resolveMediaUrl("/api/media/42", "http://127.0.0.1:8000/api"),
    "http://127.0.0.1:8000/api/media/42",
  );
});

test("keeps provider, blob, and data media URLs unchanged", () => {
  for (const url of [
    "https://cdn.example/photo.jpg",
    "blob:http://localhost:5173/preview",
    "data:image/png;base64,abc",
  ]) {
    assert.equal(resolveMediaUrl(url, "http://127.0.0.1:8000/api"), url);
  }
});

test("turns legacy audio and sticker messages into displayable attachments", () => {
  assert.deepEqual(
    displayAttachments(
      { media_type: "audio", media_url: "/api/media/71" },
      "http://127.0.0.1:8000/api",
    ),
    [{ media_type: "audio", media_url: "http://127.0.0.1:8000/api/media/71" }],
  );
  assert.deepEqual(
    displayAttachments(
      { media_type: "sticker", media_url: "https://cdn.example/sticker.webp" },
      "http://127.0.0.1:8000/api",
    ),
    [{ media_type: "sticker", media_url: "https://cdn.example/sticker.webp" }],
  );
});

test("hides the legacy TikTok media prefix but keeps the customer message", () => {
  assert.equal(
    displayMessageText("[Khách gửi nội dung TikTok] Khách gửi một sticker trên TikTok.", "tiktok"),
    "Khách gửi một sticker trên TikTok.",
  );
  assert.equal(displayMessageText("[Khách gửi nội dung TikTok] hello", "telegram"), "[Khách gửi nội dung TikTok] hello");
});

test("hides Meta sender metadata and collapses a matching imported bot echo", () => {
  const messages = [
    { message_id: 1, direction: "outbound", sender_type: "bot", content: "Chào bạn! Mình có thể giúp bạn tìm sản phẩm nào ạ?", received_at: "2026-10-07T13:56:00Z" },
    { message_id: 2, direction: "outbound", sender_type: "staff", raw_payload: { source: "meta_history_import" }, content: "Chào bạn! Mình có thể giúp bạn tìm sản phẩm nào ạ?\nĐã gửi\nNgười gửi: Shop", received_at: "2026-10-07T13:56:18Z" },
  ];

  assert.equal(displayMessageText(messages[1].content, "facebook", "outbound"), "Chào bạn! Mình có thể giúp bạn tìm sản phẩm nào ạ?");
  assert.deepEqual(visibleConversationMessages(messages, "facebook").map((message) => message.message_id), [1]);
  assert.match(appVue, /v-for="message in visibleMessages"/);
});

test("keeps a separate repeated Meta message outside the echo time window", () => {
  const messages = [
    { message_id: 1, direction: "outbound", sender_type: "bot", content: "Chào bạn!", received_at: "2026-10-07T13:00:00Z" },
    { message_id: 2, direction: "outbound", sender_type: "staff", raw_payload: { source: "meta_history_import" }, content: "Chào bạn!", received_at: "2026-10-07T13:10:00Z" },
  ];

  assert.equal(visibleConversationMessages(messages, "instagram").length, 2);
});

test("hides an adjacent imported Meta echo when the provider omitted its timestamp", () => {
  const messages = [
    { message_id: 1, direction: "outbound", sender_type: "bot", content: "Bạn cần hỗ trợ gì cụ thể?", received_at: "2026-10-07T13:56:00Z" },
    { message_id: 2, direction: "outbound", sender_type: "staff", raw_payload: { source: "meta_history_import", timestamp_accuracy: "unavailable_from_source" }, content: "Bạn cần hỗ trợ gì cụ thể?", received_at: null },
  ];

  assert.deepEqual(visibleConversationMessages(messages, "instagram").map((message) => message.message_id), [1]);
});

test("audio message bubbles reserve room for a seek bar", () => {
  assert.match(appVue, /bubble-with-audio/);
  assert.match(stylesheet, /\.bubble-with-audio\s*\{[\s\S]*?width:\s*min\(320px,\s*100%\)/);
  assert.match(stylesheet, /\.bubble-with-audio\s*\{[\s\S]*?max-width:\s*min\(320px,\s*100%\)/);
  assert.match(stylesheet, /\.bubble-with-audio\s*\{[\s\S]*?min-width:\s*min\(240px,\s*100%\)/);
  assert.match(stylesheet, /\.message-audio\s*\{[\s\S]*?width:\s*100%/);
});
