/** Small authenticated API wrapper; tenant identity comes only from bearer auth. */
export function createApiClient({ baseUrl, getToken } = {}) {
  const apiBase = String(baseUrl || "").replace(/\/$/, "");
  return {
    fetch(input, init = {}) {
      const headers = new Headers(init.headers || {});
      const token = typeof getToken === "function" ? getToken() : "";
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
