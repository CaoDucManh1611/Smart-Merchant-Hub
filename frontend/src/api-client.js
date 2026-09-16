import { readAuthToken } from "./auth-context.js";

/** Attach only bearer auth; the server resolves tenant identity. */
export function apiFetch(input, init = {}) {
  const headers = new Headers(init.headers || {});
  const token = readAuthToken();
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  return fetch(input, { ...init, headers });
}

/** Injectable variant retained for tests and non-browser consumers. */
export function createApiClient({ baseUrl, getToken } = {}) {
  const apiBase = String(baseUrl || "").replace(/\/$/, "");
  return {
    fetch(input, init = {}) {
      const headers = new Headers(init.headers || {});
      const token = typeof getToken === "function" ? getToken() : readAuthToken();
      if (token && !headers.has("Authorization")) {
        headers.set("Authorization", `Bearer ${token}`);
      }
      const target = typeof input === "string" && input.startsWith("/") && apiBase
        ? `${apiBase}${input}`
        : input;
      return fetch(target, { ...init, headers });
    },
  };
}
