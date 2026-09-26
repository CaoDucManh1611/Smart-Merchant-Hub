import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { NodeTypes } from "@vue/compiler-dom";
import { parse } from "@vue/compiler-sfc";

import { formatDate, formatDateTime, formatMoney, locale, setLocale, t } from "../src/i18n.js";
import { transformVueTemplateText } from "../src/i18n-vue-plugin.js";
import { channelCapacityState, connectionStateMeta, paymentStatusMeta, subscriptionStatusMeta } from "../src/platform-admin-utils.js";

test("UI locale switches, persists, and falls back to Vietnamese for untranslated copy", () => {
  const saved = new Map();
  globalThis.localStorage = {
    getItem: (key) => saved.get(key) ?? null,
    setItem: (key, value) => saved.set(key, value),
  };

  assert.equal(setLocale("en"), true);
  assert.equal(locale.value, "en");
  assert.equal(saved.get("smh-ui-locale"), "en");
  assert.equal(t("Hộp thư & Khách hàng 360"), "Inbox & Customer 360");
  assert.equal(t("Cụm từ chưa dịch"), "Cụm từ chưa dịch");
  assert.equal(t("  Hộp thư & Khách hàng 360\n"), "  Inbox & Customer 360\n");
  assert.equal(setLocale("fr"), false);
  assert.equal(locale.value, "en");
  setLocale("vi");
  delete globalThis.localStorage;
});

test("Vietnamese CRM terminology is simplified consistently across pages", () => {
  setLocale("vi");
  assert.equal(t("Mô hình kinh doanh & module"), "Loại hình kinh doanh & tính năng");
  assert.equal(t("Trường khách hàng & pipeline"), "Thông tin khách hàng & quy trình bán hàng");
  assert.equal(t("RAG · SLA · CSAT · workflow · tenant · webhook · token · API · OTP · FAQ"), "tra cứu trong kho kiến thức · thời hạn hỗ trợ · điểm hài lòng · quy trình tự động · shop · điểm nhận sự kiện · mã truy cập · kết nối hệ thống · xác minh · câu hỏi thường gặp");
  assert.equal(t("Mã OTP 6 số"), "Mã xác minh 6 số");
  assert.equal(t("Đoạn kiến thức"), "Mục kiến thức");
  assert.equal(t("Hội thoại mới"), "Cuộc trò chuyện mới");
  assert.equal(t("CRM đang hoạt động"), "Hệ thống đang hoạt động");
  assert.equal(t("Lõi CRM"), "Chức năng chính");
  assert.equal(t("CRM LINH HOẠT"), "TÙY CHỈNH HỆ THỐNG");
  assert.equal(t("Dữ liệu CRM"), "Dữ liệu hệ thống quản lý khách hàng");
  assert.equal(t("Tài khoản & phiên đăng nhập"), "Tài khoản & phiên đăng nhập");
  assert.equal(t("CÀI ĐẶT SHOP"), "CÀI ĐẶT SHOP");
  assert.doesNotMatch(t("Gói CRM:"), /CRM/i);
  assert.doesNotMatch(t("Lõi CRM dùng chung cho mọi mô hình; bộ ngành có thể bật riêng. Tắt module chỉ ẩn và khóa thao tác, không xóa dữ liệu."), /CRM/i);
});

test("English UI copy replaces CRM jargon with plain language", () => {
  setLocale("en");
  assert.equal(t("CRM đang hoạt động"), "Workspace is active");
  assert.equal(t("Lõi CRM"), "Core features");
  assert.equal(t("CRM Chatbot đa kênh"), "Multichannel customer service chatbot");
  assert.equal(t("Tài khoản & phiên đăng nhập"), "Account & sign-in session");
  assert.equal(t("CÀI ĐẶT SHOP"), "SHOP SETTINGS");
  assert.equal(t("Loại hình kinh doanh & tính năng"), "Business type & features");
  assert.equal(t("Chức năng chính"), "Core features");
  assert.equal(t("TÙY CHỈNH QUY TRÌNH"), "CUSTOMIZE WORKFLOWS");
  assert.doesNotMatch(t("Gói CRM:"), /CRM/i);
  setLocale("vi");
});

test("Vue static copy and accessible labels are routed through the active locale", () => {
  const source = '<template><button aria-label="Đóng">Lưu thay đổi</button><input placeholder="Tìm khách hàng" /><span>{{ connected ? \'Đã kết nối\' : \'Chưa kết nối\' }}</span><button :aria-label="`Xóa ${name}`" /></template>';
  const output = transformVueTemplateText(source, "/frontend/src/Probe.vue");
  assert.match(output, /\{\{ \$t\("Lưu thay đổi"\) \}\}/);
  assert.match(output, /:aria-label='\$t\("Đóng"\)'/);
  assert.match(output, /:placeholder='\$t\("Tìm khách hàng"\)'/);
  assert.match(output, /\{\{ \$t\(connected \? 'Đã kết nối' : 'Chưa kết nối'\) \}\}/);
  assert.match(output, /:aria-label="\$t\(`Xóa \$\{name\}`\)"/);
});

test("English covers all Vietnamese static Vue copy and localizes dates and currency", () => {
  const sourceRoot = fileURLToPath(new URL("../src/", import.meta.url));
  const findVueFiles = (directory) => readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? findVueFiles(path) : entry.name.endsWith(".vue") ? [path] : [];
  });
  const untranslated = [];
  const untranslatedExpressionCopy = new Set();
  const vietnamese = (text) => [...text].some((character) => (
    character.codePointAt(0) > 127 && /\p{Script=Latin}/u.test(character)
  ));

  setLocale("en");
  for (const file of findVueFiles(sourceRoot)) {
    const { descriptor, errors } = parse(readFileSync(file, "utf8"), { filename: file });
    assert.deepEqual(errors, [], `Could not parse ${file}`);
    const walk = (node) => {
      if (node.type === NodeTypes.TEXT && vietnamese(node.content) && t(node.content) === node.content) {
        untranslated.push(`${file}: ${node.content.trim()}`);
      }
      if (node.type === NodeTypes.ELEMENT) {
        for (const prop of node.props) {
          if (prop.type === NodeTypes.ATTRIBUTE && prop.value && vietnamese(prop.value.content)
            && !prop.value.content.includes("{{") && t(prop.value.content) === prop.value.content) {
            untranslated.push(`${file}: ${prop.name}=${prop.value.content}`);
          }
        }
      }
      const checkExpression = (expression) => {
        if (!expression) return;
        const strings = [...expression.matchAll(/'((?:\\.|[^'\\])*)'|"((?:\\.|[^"\\])*)"|`([^`]*)`/g)];
        for (const match of strings) {
          const value = match[1] ?? match[2] ?? match[3];
          const phrases = match[3] === undefined ? [value] : value.replace(/\$\{[^}]*\}/g, "\0").split("\0");
          for (const phrase of phrases.map((item) => item.trim()).filter((item) => vietnamese(item) && t(item) === item)) {
            untranslatedExpressionCopy.add(phrase);
          }
        }
      };
      if (node.type === NodeTypes.INTERPOLATION) checkExpression(node.content?.content);
      if (node.type === NodeTypes.ELEMENT) {
        for (const prop of node.props) {
          if (prop.type === NodeTypes.DIRECTIVE && prop.name === "bind") checkExpression(prop.exp?.content);
        }
      }
      for (const child of node.children || []) walk(child);
    };
    if (descriptor.template?.ast) walk(descriptor.template.ast);
  }

  assert.deepEqual(untranslated, []);
  const missingExpressions = [...untranslatedExpressionCopy];
  assert.equal(missingExpressions.length, 0, missingExpressions.join("\n"));
  assert.match(formatMoney(1200000), /1,200,000/);
  assert.match(formatDate("2026-09-26"), /Sep|September/);
  assert.match(formatDateTime("2026-09-26T08:30:00Z"), /AM|PM/);
  setLocale("vi");
  assert.match(formatMoney(1200000), /1\.200\.000/);
});

test("English localizes derived CRM status labels and channel limit messages", () => {
  const labels = [
    "Mới tạo", "Chờ nhân viên xác nhận", "Đang đóng gói", "Đang giao", "Đã giao", "Hoàn thành", "Chưa rõ",
    "Đang mở", "Đã xử lý", "Đã đóng", "Thấp", "Bình thường", "Cao", "Khẩn cấp", "Bản nháp", "Đã gửi",
    "Đã nhận một phần", "Đã nhận đủ", "Đã hoàn tất", "Chưa thanh toán", "Thanh toán một phần", "Đã thanh toán",
    "Chưa bàn giao", "Đang vận chuyển", "Giao thất bại", "Đã hoàn", "Đang huấn luyện", "Sẵn sàng", "Lỗi",
    "Đã lưu trữ", "Đang dùng", "Chờ xử lý", "Đang xử lý", "Đang chuẩn bị", "Chưa xử lý được", "đọc tài liệu",
    "phân tích nội dung", "xử lý nội dung", "hoàn thiện", "hoàn tất", "Tin nhắn mới", "Tạo phiếu hỗ trợ",
    "Gắn nhãn", "Phân công", "Hội thoại", "Đơn bán", "Kênh kết nối", "Lượt trợ lý", "Đoạn kiến thức",
  ];
  setLocale("en");
  assert.deepEqual(labels.filter((label) => t(label) === label), []);
  assert.equal(subscriptionStatusMeta("active").label, "Active");
  assert.equal(paymentStatusMeta("paid").label, "Paid");
  assert.equal(connectionStateMeta("connected").label, "Connected");
  assert.match(channelCapacityState({ plan_code: "demo", plan_name: "Gói Demo" }).reason, /^The Demo plan/);
  assert.equal(t("Đơn #42"), "Order #42");
  assert.equal(t("Hạn Sep 26, 2026"), "Due Sep 26, 2026");
  assert.equal(t("Xem chi tiết (3 hoạt động gần nhất)"), "View details (3 recent activities)");
  assert.equal(t("Lịch sử thu (2)"), "Payment history (2)");
  assert.equal(t("Gói đã chọn cho phép kết nối tối đa 4 nền tảng. Việc kết nối thực tế được thực hiện duy nhất tại mục Kết nối mạng xã hội."), "The selected plan allows up to 4 platforms. Connect platforms from Social Connections.");
  setLocale("vi");
});

test("English localizes dynamic CRM and chatbot plan names and descriptions", () => {
  const planCopy = [
    ["Gói Demo", "Demo Plan"],
    ["Gói Thường", "Standard Plan"],
    ["Gói VIP", "VIP Plan"],
    ["Gói Scale", "Scale Plan"],
    ["Gói Premium", "Premium Plan"],
    ["Dùng thử CRM, chưa mở kết nối kênh.", "Try the customer management system; channel connections are not included."],
    ["Gói gọn nhẹ cho shop mới bắt đầu chăm khách.", "A lightweight plan for shops starting with customer care."],
    ["Gói cân bằng cho shop cần nhiều kênh và đội ngũ chăm khách.", "A balanced plan for shops that need more channels and a customer care team."],
    ["Gói dùng thử 0 đồng để xem giao diện và quy trình CRM. Chưa mở kết nối mạng xã hội.", "Free trial to explore the customer management interface and workflows. Social connections are not included."],
    ["Gói gọn nhẹ cho shop mới bắt đầu chăm khách và quản lý hội thoại.", "A lightweight plan for new shops starting with customer care and conversation management."],
    ["Gói cân bằng cho shop cần nhiều kênh và đội ngũ chăm khách hằng ngày.", "A balanced plan for shops that need more channels and a team for daily customer care."],
    ["Gói cho shop vận hành đồng thời trên 4 nền tảng.", "For shops operating across 4 platforms at the same time."],
    ["Gói đầy đủ cho shop vận hành đủ 6 nền tảng.", "Full-featured plan for shops operating across all 6 platforms."],
    ["Trợ lý Demo", "Assistant Demo"],
    ["Trợ lý Cơ bản", "Basic Assistant"],
    ["Trợ lý Nâng cao", "Advanced Assistant"],
    ["Trợ lý Scale", "Scale Assistant"],
    ["Trợ lý Toàn diện", "Full-Service Assistant"],
    ["Xem thử cách trợ lý tiếp nhận và trả lời hội thoại.", "Preview how the assistant receives and replies to conversations."],
    ["Bot trả lời FAQ và hỗ trợ các câu hỏi thường gặp.", "Answers FAQs and common questions."],
    ["Bot tư vấn theo kho tri thức, sản phẩm và chuyển nhân viên.", "Advises using your knowledge base and products, and hands off to staff."],
    ["Bot tư vấn cho shop vận hành nhiều kênh và quy trình hơn.", "Advises shops running more channels and workflows."],
    ["Bot được cài đặt, theo dõi và tối ưu riêng cho shop.", "Configured, monitored, and optimized specifically for your shop."],
  ];
  setLocale("en");
  for (const [source, expected] of planCopy) assert.equal(t(source), expected);
  setLocale("vi");
});

test("English localizes dynamic workspace business profile labels and descriptions", () => {
  const profiles = [
    ["Bán lẻ", "Retail"],
    ["Sản phẩm, đơn bán và tồn kho.", "Products, sales orders, and inventory."],
    ["Dịch vụ theo lịch", "Appointment services"],
    ["Khách hàng, hội thoại, công việc và chăm sóc.", "Customers, conversations, tasks, and customer care."],
    ["Dự án / B2B", "Projects / B2B"],
    ["Doanh nghiệp, cơ hội và pipeline bán hàng.", "Companies, opportunities, and sales pipeline."],
    ["Đa dịch vụ", "Multiple business models"],
    ["Kết hợp nhiều mô hình trong cùng shop.", "Combine multiple business models in one shop."],
    ["Đã lưu mô hình và module cho shop. Dữ liệu cũ vẫn được giữ nguyên.", "The shop model and modules were saved. Existing data has been preserved."],
    ["Chưa tải được mô hình shop.", "Could not load the shop model. Please try again."],
    ["Chưa lưu được cấu hình mô hình shop.", "Could not save the shop model configuration. Please try again."],
  ];
  setLocale("en");
  for (const [source, expected] of profiles) assert.equal(t(source), expected);
  const appSource = readFileSync(new URL("../src/App.vue", import.meta.url), "utf8");
  assert.match(appSource, /\$t\(profile\.name\)/);
  assert.match(appSource, /\$t\(profile\.desc\)/);
  assert.match(appSource, /\$t\(workspaceConfigNotice\)/);
  assert.match(appSource, /\$t\(workspaceConfigError\)/);
  setLocale("vi");
});
