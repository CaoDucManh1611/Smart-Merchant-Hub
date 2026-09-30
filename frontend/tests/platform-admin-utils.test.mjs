import assert from "node:assert/strict";
import test from "node:test";

import {
  channelCapacityState,
  connectionStateMeta,
  latestPayment,
  paymentStatusMeta,
  platformQuotaCards,
  subscriptionStatusMeta,
} from "../src/platform-admin-utils.js";

test("platform quota cards use business labels for staff, channels and knowledge capacity", () => {
  const cards = platformQuotaCards({
    resources: {
      staff_users: { used: 3, limit: 5, percent: 60 },
      connected_channels: { used: 2, limit: 2, percent: 100, near_limit: true },
      documents: { used: 12, limit: 20, percent: 60 },
      rag_chunks: { used: 420, limit: 500, percent: 84, near_limit: true },
    },
  });

  assert.deepEqual(cards.map((item) => item.key), [
    "connected_channels",
    "staff_users",
    "documents",
    "rag_chunks",
  ]);
  assert.equal(cards[0].label, "Kênh kết nối");
  assert.equal(cards[1].label, "Nhân viên");
  assert.equal(cards[2].label, "Tài liệu");
  assert.equal(cards[3].label, "Dung lượng tra cứu");
  assert.equal(cards[3].nearLimit, true);
});
test("payment and subscription states are presented in Vietnamese", () => {
  assert.equal(subscriptionStatusMeta("active").label, "Đang hoạt động");
  assert.equal(subscriptionStatusMeta("past_due").tone, "danger");
  assert.equal(paymentStatusMeta("paid").label, "Đã thanh toán");
  assert.equal(paymentStatusMeta("refunded").label, "Đã hoàn tiền");
});

test("latest payment selects the newest payment without mutating input", () => {
  const rows = [
    { id: 1, status: "paid", created_at: "2026-09-01T00:00:00Z" },
    { id: 2, status: "pending", created_at: "2026-09-03T00:00:00Z" },
  ];
  const snapshot = structuredClone(rows);
  assert.equal(latestPayment(rows).id, 2);
  assert.deepEqual(rows, snapshot);
});

test("channel capacity always explains why another channel cannot be connected", () => {
  assert.deepEqual(
    channelCapacityState({ plan_name: "Demo", resources: { connected_channels: { used: 0, limit: 0 } } }),
    {
      blocked: true,
      used: 0,
      limit: 0,
      reason: "Gói Demo chưa mở kết nối kênh. Hãy chọn hoặc nâng cấp gói để tiếp tục.",
    },
  );
  assert.equal(
    channelCapacityState({ plan_name: "Growth", resources: { connected_channels: { used: 3, limit: 3 } } }).reason,
    "Đã dùng 3/3 kênh của gói Growth. Hãy nâng cấp gói hoặc ngắt một kênh đang dùng.",
  );
  assert.equal(
    channelCapacityState({ plan_name: "Growth", resources: { connected_channels: { used: 2, limit: 3 } } }).blocked,
    false,
  );
});

test("connection states distinguish verifying, reconnect, error and disconnected", () => {
  assert.equal(connectionStateMeta("connected").label, "Đã kết nối");
  assert.equal(connectionStateMeta("verifying").label, "Đang xác minh");
  assert.equal(connectionStateMeta("reconnect_required").label, "Cần kết nối lại");
  assert.equal(connectionStateMeta("error").tone, "danger");
  assert.equal(connectionStateMeta("disconnected").label, "Đã ngắt");
});
