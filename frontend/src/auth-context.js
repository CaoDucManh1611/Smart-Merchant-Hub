/** Browser-side authentication state and authenticated shop helpers. */

export const AUTH_TOKEN_KEY = "crm_access_token";

export function readAuthToken(storage = window.localStorage) {
  return storage.getItem(AUTH_TOKEN_KEY) || "";
}

export function storeAuthToken(token, storage = window.localStorage) {
  if (!token) throw new Error("Không thể lưu access token rỗng.");
  storage.setItem(AUTH_TOKEN_KEY, token);
  return token;
}

export function clearAuthToken(storage = window.localStorage) {
  storage.removeItem(AUTH_TOKEN_KEY);
}

export function activeBusinessId(user) {
  const value = Number(user?.business_id);
  return Number.isInteger(value) && value > 0 ? value : null;
}

export function requireBusinessId(user) {
  const value = activeBusinessId(user);
  if (!value) throw new Error("Phiên đăng nhập chưa có shop hợp lệ.");
  return value;
}
