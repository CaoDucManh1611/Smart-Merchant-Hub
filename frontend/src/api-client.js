import { readAuthToken } from "./auth-context.js";

/** Keep browser/network implementation details out of the shop-facing UI. */
function normalizeFetchError(error) {
  const message = String(error?.message || error || "");
  if (/failed\b|networkerror|network request failed|load failed|connection refused|timeout|exception/i.test(message)) {
    // Keep network details in the console/cause only.  Shop users should see
    // a short, actionable message without infrastructure terminology.
    const friendly = new Error("Chưa thể tải thông tin lúc này. Vui lòng thử lại sau.");
    friendly.cause = error;
    return friendly;
  }
  return error;
}

/** Attach only bearer auth; the server resolves tenant identity. */
export function apiFetch(input, init = {}) {
  const headers = new Headers(init.headers || {});
  const token = readAuthToken();
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  return fetch(input, { ...init, headers }).catch((error) => {
    throw normalizeFetchError(error);
  });
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
      return fetch(target, { ...init, headers }).catch((error) => {
        throw normalizeFetchError(error);
      });
    },
  };
}
