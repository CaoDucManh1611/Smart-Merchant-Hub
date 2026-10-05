import { clearAuthToken, readAuthToken } from "./auth-context.js";

export const AUTH_EXPIRED_EVENT = "smh:auth-expired";

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
export async function apiFetch(input, init = {}) {
  const headers = new Headers(init.headers || {});
  const token = readAuthToken();
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  try {
    const response = await fetch(input, { ...init, headers });
    if (response.status === 401 && token) {
      // An MFA-protected session is still valid while it waits for its code.
      // Do not erase that token just because an endpoint asks for this step.
      const detail = await response.clone().json().catch(() => ({}));
      const code = detail?.detail?.code;
      if (code !== "mfa_required") {
        clearAuthToken();
        if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
      }
    }
    return response;
  } catch (error) {
    throw normalizeFetchError(error);
  }
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
