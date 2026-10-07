import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const appSource = fs.readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");
const styleSource = fs.readFileSync(new URL("../src/style.css", import.meta.url), "utf8");
const templateSource = appSource.slice(appSource.indexOf("<template>"), appSource.lastIndexOf("</template>"));

test("knowledge-base copy describes retrieval without claiming automatic training", () => {
  assert.match(templateSource, /Việc thêm tài liệu không tự thay đổi cách trợ lý được thiết lập/);
  assert.doesNotMatch(templateSource, /để trợ lý tự động học và trả lời khách hàng/);
});

test("customer personalization uses compact facts and keeps opt-out controls visible", () => {
  assert.match(templateSource, /Cá nhân hóa khách hàng/);
  assert.match(templateSource, /Chỉ lưu thông tin tóm tắt/);
  assert.match(templateSource, /Ngừng lưu và xóa sở thích suy ra/);
  assert.match(appSource, /Đánh giá chưa tự thay đổi cách trợ lý trả lời/);
  assert.doesNotMatch(templateSource, /vector cho từng tin/);
});

test("topic summary describes its purpose in plain language", () => {
  assert.match(templateSource, /Chủ đề khách thường hỏi/);
  assert.match(templateSource, /Tổng hợp nhu cầu xuất hiện nhiều trong 30 ngày qua/);
});

test("experiment lab shows production-readiness boundaries", () => {
  assert.match(templateSource, /Khu vực thử nghiệm nội bộ/);
  assert.match(templateSource, /chưa tự thay đổi câu trả lời gửi khách/);
  assert.match(templateSource, /So sánh &amp; dự đoán/);
  assert.match(templateSource, /Chạy đánh giá mẫu/);
  assert.doesNotMatch(templateSource, />Huấn luyện<\/button>/);
  assert.match(styleSource, /\.ai-readiness-grid/);
  assert.match(styleSource, /\.ai-readiness-badge\.experimental/);
});

test("approved reply trials can affect live chat only through bounded response styles", () => {
  assert.match(appSource, /runtime_binding: "chatbot_auto_reply"/);
  assert.match(appSource, /approved_arms: approvedArms/);
  assert.match(appSource, /const responseStyles = \["balanced", "concise", "detailed"\]/);
  assert.match(templateSource, /only the approved|cân bằng, ngắn gọn hoặc chi tiết/);
});
