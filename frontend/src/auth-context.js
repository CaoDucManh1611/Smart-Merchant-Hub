/** Browser-side authentication state shared by API helpers and the shell. */

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
