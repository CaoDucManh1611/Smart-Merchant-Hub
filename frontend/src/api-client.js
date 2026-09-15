import { readAuthToken } from "./auth-context.js";

/**
 * Attach only the bearer credential. Tenant identity is resolved by the API
 * from the authenticated session; the browser must never select a shop with
 * a hardcoded id or tenant-selection header.
 */
export function apiFetch(input, init = {}) {
  const headers = new Headers(init.headers || {});
  const token = readAuthToken();
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  return fetch(input, { ...init, headers });
}
