import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { displayAttachments, resolveMediaUrl } from "../src/media-utils.js";

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

test("audio message bubbles reserve room for a seek bar", () => {
  assert.match(appVue, /bubble-with-audio/);
  assert.match(stylesheet, /\.bubble-with-audio\s*\{[\s\S]*?width:\s*min\(320px,\s*100%\)/);
  assert.match(stylesheet, /\.bubble-with-audio\s*\{[\s\S]*?max-width:\s*min\(320px,\s*100%\)/);
  assert.match(stylesheet, /\.bubble-with-audio\s*\{[\s\S]*?min-width:\s*min\(240px,\s*100%\)/);
  assert.match(stylesheet, /\.message-audio\s*\{[\s\S]*?width:\s*100%/);
});
