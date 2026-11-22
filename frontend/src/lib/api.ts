// The bot's API lives under /api/v1/bot on the platform API (same host as the exchange).
const API_ORIGIN = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export const getApiBaseUrl = () => `${API_ORIGIN}/api/v1/bot`;

export const getWsBaseUrl = () => `${API_ORIGIN.replace(/^http/, "ws")}/api/v1/bot/ws/`;

/** Signed-in users can change bot settings and the watchlist; reads are public. */
function authHeaders(): Record<string, string> {
  try {
    const token = typeof window !== "undefined" ? localStorage.getItem("auth_token") : null;
    return token ? { Authorization: `Bearer ${token}` } : {};
  } catch {
    return {};
  }
}

async function request(endpoint: string, init: RequestInit = {}) {
  const response = await fetch(`${getApiBaseUrl()}${endpoint}`, {
    ...init,
    headers: { ...(init.body ? { "Content-Type": "application/json" } : {}), ...authHeaders(), ...(init.headers || {}) },
  });
  if (!response.ok) {
    let detail = `API error ${response.status}`;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {}
    if (response.status === 401) detail = "Sign in to change the bot";
    throw new Error(detail);
  }
  const text = await response.text();
  return text ? JSON.parse(text) : { success: true };
}

export const api = {
  get: (endpoint: string) => request(endpoint),
  post: (endpoint: string, data?: unknown) =>
    request(endpoint, { method: "POST", body: data ? JSON.stringify(data) : undefined }),
  delete: (endpoint: string) => request(endpoint, { method: "DELETE" }),
};
