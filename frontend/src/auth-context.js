/** Return the shop selected by the authenticated bearer session. */
export function activeBusinessId(user) {
  const value = Number(user?.business_id);
  return Number.isInteger(value) && value > 0 ? value : null;
}

export function requireBusinessId(user) {
  const value = activeBusinessId(user);
  if (!value) throw new Error("Phiên đăng nhập chưa có shop hợp lệ.");
  return value;
}
