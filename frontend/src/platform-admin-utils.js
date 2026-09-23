const asNumber = (value, fallback = 0) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};

const normalized = (value) => String(value || "").trim().toLowerCase();

export function subscriptionStatusMeta(status) {
  const value = normalized(status);
  const states = {
    active: { label: "Đang hoạt động", tone: "success" },
    trialing: { label: "Đang dùng thử", tone: "info" },
    pending: { label: "Chờ duyệt", tone: "warning" },
    past_due: { label: "Quá hạn thanh toán", tone: "danger" },
    suspended: { label: "Tạm ngưng", tone: "danger" },
    cancelled: { label: "Đã hủy", tone: "muted" },
    expired: { label: "Đã hết hạn", tone: "muted" },
  };
  return states[value] || { label: status ? "Chưa xác định" : "Chưa có gói", tone: "muted" };
}

export function paymentStatusMeta(status) {
  const value = normalized(status);
  const states = {
    paid: { label: "Đã thanh toán", tone: "success" },
    pending: { label: "Chờ thanh toán", tone: "warning" },
    processing: { label: "Đang xử lý", tone: "info" },
    failed: { label: "Thanh toán lỗi", tone: "danger" },
    refunded: { label: "Đã hoàn tiền", tone: "muted" },
    cancelled: { label: "Đã hủy", tone: "muted" },
  };
  return states[value] || { label: status ? "Chưa xác định" : "Chưa có thanh toán", tone: "muted" };
}

export function connectionStateMeta(status) {
  const value = normalized(status);
  const states = {
    connected: { label: "Đã kết nối", tone: "success" },
    active: { label: "Đã kết nối", tone: "success" },
    verifying: { label: "Đang xác minh", tone: "warning" },
    reconnect_required: { label: "Cần kết nối lại", tone: "warning" },
    error: { label: "Lỗi kết nối", tone: "danger" },
    disconnected: { label: "Đã ngắt", tone: "muted" },
  };
  return states[value] || { label: "Chưa xác định", tone: "muted" };
}

export function latestPayment(payments) {
  if (!Array.isArray(payments) || !payments.length) return null;
  return [...payments].sort((left, right) => {
    const rightTime = new Date(right?.paid_at || right?.updated_at || right?.created_at || 0).getTime();
    const leftTime = new Date(left?.paid_at || left?.updated_at || left?.created_at || 0).getTime();
    if (rightTime !== leftTime) return rightTime - leftTime;
    return asNumber(right?.id) - asNumber(left?.id);
  })[0];
}

export function platformQuotaCards(quota) {
  const resources = quota?.resources || quota || {};
  const definitions = [
    ["connected_channels", "Kênh kết nối"],
    ["staff_users", "Nhân viên"],
    ["documents", "Tài liệu"],
    ["rag_chunks", "Dung lượng tra cứu"],
  ];

  return definitions.map(([key, label]) => {
    const resource = resources[key] || {};
    const limit = resource.limit === null || resource.limit === undefined ? null : asNumber(resource.limit);
    const used = asNumber(resource.used);
    const percent = limit === null
      ? 0
      : Math.max(0, Math.min(100, asNumber(resource.percent, limit > 0 ? (used / limit) * 100 : 100)));
    const exceeded = Boolean(resource.exceeded) || (limit !== null && used > limit);
    const nearLimit = !exceeded && (Boolean(resource.near_limit) || (limit !== null && limit > 0 && used / limit >= 0.8));
    return { key, label, used, limit, percent, nearLimit, exceeded };
  });
}

export function channelCapacityState(quotaSnapshot) {
  const channel = quotaSnapshot?.resources?.connected_channels || {};
  const used = asNumber(channel.used);
  const limit = channel.limit === null || channel.limit === undefined ? null : Math.max(0, asNumber(channel.limit));
  const planName = String(quotaSnapshot?.plan_name || quotaSnapshot?.plan_code || "gói hiện tại");
  const demoPlan = normalized(quotaSnapshot?.plan_code || quotaSnapshot?.plan_name) === "demo";
  const blocked = limit === 0 || (limit !== null && used >= limit);

  if (limit === 0 || demoPlan) {
    return {
      blocked: true,
      used,
      limit: 0,
      reason: "Gói Demo chưa mở kết nối kênh. Hãy chọn hoặc nâng cấp gói để tiếp tục.",
    };
  }
  if (blocked) {
    return {
      blocked: true,
      used,
      limit,
      reason: `Đã dùng ${used}/${limit} kênh của gói ${planName}. Hãy nâng cấp gói hoặc ngắt một kênh đang dùng.`,
    };
  }
  return {
    blocked: false,
    used,
    limit,
    reason: limit === null
      ? `Gói ${planName} không giới hạn số kênh kết nối.`
      : `Đang dùng ${used}/${limit} kênh của gói ${planName}.`,
  };
}
