import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const appSource = fs.readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");
const styleSource = fs.readFileSync(new URL("../src/style.css", import.meta.url), "utf8");
const templateSource = appSource.slice(appSource.indexOf("<template>"), appSource.lastIndexOf("</template>"));

test("knowledge-base copy describes retrieval without claiming automatic training", () => {
  assert.match(templateSource, /Tài liệu được lập chỉ mục, không dùng để tự huấn luyện mô hình/);
  assert.doesNotMatch(templateSource, /để trợ lý tự động học và trả lời khách hàng/);
});

test("conversation feedback is presented as quality data, not autonomous learning", () => {
  assert.match(templateSource, /Thu thập mẫu và phản hồi/);
  assert.match(templateSource, /CHƯA TỰ HỌC/);
  assert.match(templateSource, /Phản hồi chỉ dùng để thống kê và chưa tự thay đổi câu trả lời/);
  assert.match(appSource, /Đánh giá chưa tự thay đổi cách trợ lý trả lời/);
  assert.doesNotMatch(templateSource, /Tự cải thiện từ đánh giá của khách/);
});

test("topic summary clearly identifies its current rule-based limitation", () => {
  assert.match(templateSource, /Chủ đề khách thường hỏi/);
  assert.match(templateSource, /Đây chưa phải học không giám sát/);
  assert.match(templateSource, /chưa được dùng để tự huấn luyện hoặc tự điều chỉnh trợ lý/);
});

test("experiment lab shows production-readiness boundaries", () => {
  assert.match(templateSource, /Khu vực thử nghiệm nội bộ/);
  assert.match(templateSource, /chưa tự thay đổi câu trả lời đang gửi cho khách/);
  assert.match(templateSource, /A\/B và dự đoán/);
  assert.match(templateSource, /Chạy đánh giá mẫu/);
  assert.doesNotMatch(templateSource, />Huấn luyện<\/button>/);
  assert.match(styleSource, /\.ai-readiness-grid/);
  assert.match(styleSource, /\.ai-readiness-badge\.experimental/);
});
