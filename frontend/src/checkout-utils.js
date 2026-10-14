const tiers = Object.freeze({ demo: 0, starter: 1, growth: 2, scale: 3, pro: 4, enterprise: 4 });

export function checkoutAmount(quotedAmount, payment, catalogueAmount) {
  return payment?.amount ?? quotedAmount ?? catalogueAmount ?? null;
}

export function planChangeKind(current, selected) {
  if (!current) return 'new';
  if (!selected || current.code === selected.code) return 'switch';
  if (current.code in tiers && selected.code in tiers) {
    return tiers[selected.code] < tiers[current.code] ? 'downgrade' : 'upgrade';
  }
  return Number(selected.raw_price ?? 0) < Number(current.raw_price ?? 0) ? 'downgrade' : 'upgrade';
}

export function checkoutRequestLabel(status) {
  return { awaiting_payment: 'Đang chờ thanh toán', pending: 'Đang chờ admin duyệt', active: 'Gói đã được kích hoạt', cancelled: 'Yêu cầu đã bị từ chối hoặc hủy', expired: 'Yêu cầu đã hết hiệu lực' }[status] || 'Đã ghi nhận yêu cầu';
}
