/**
 * REST client.
 *
 * By default every call goes to the same origin, which the Vite dev server
 * proxies to FastAPI (see vite.config.js). Set VITE_API_BASE to point the UI at
 * a backend on another host.
 *
 * The session token is kept in localStorage and attached as a bearer header on
 * every request; the websocket carries it in the query string instead, because
 * browsers cannot set headers on a WebSocket handshake.
 */

const API_BASE = (import.meta.env?.VITE_API_BASE ?? "").replace(/\/+$/, "");
const WS_BASE = (import.meta.env?.VITE_WS_BASE ?? "").replace(/\/+$/, "");

const TOKEN_KEY = "hearth.token";

export function getToken() {
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token) {
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable - the session still works for this tab */
  }
}

export class ApiError extends Error {
  constructor(message, status, code = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

function describeDetail(detail, fallback) {
  if (!detail) return fallback;
  if (typeof detail === "string") return detail;
  // FastAPI validation errors arrive as a list of {loc, msg, type}.
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        const field = Array.isArray(item.loc) ? item.loc[item.loc.length - 1] : null;
        return field ? `${field}: ${item.msg}` : item.msg;
      })
      .join(", ");
  }
  // Structured errors from the quota layer: { code, message }.
  if (typeof detail === "object" && detail.message) return detail.message;
  return fallback;
}

function errorCode(detail) {
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    return detail.code ?? null;
  }
  return null;
}

async function request(path, { method = "GET", body, signal, token } = {}) {
  const authToken = token ?? getToken();
  const headers = {};
  if (body) headers["Content-Type"] = "application/json";
  if (authToken) headers.Authorization = `Bearer ${authToken}`;

  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      signal,
      headers: Object.keys(headers).length ? headers : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (error) {
    if (error?.name === "AbortError") throw error;
    throw new ApiError(
      "Cannot reach the Hearth backend. Is it running on port 8000?",
      0,
    );
  }

  if (!response.ok) {
    let detail = null;
    try {
      const payload = await response.json();
      detail = payload?.detail;
    } catch {
      /* non JSON error body */
    }
    throw new ApiError(
      describeDetail(detail, `Request failed (${response.status}).`),
      response.status,
      errorCode(detail),
    );
  }

  if (response.status === 204) return null;
  return response.json();
}

/** Websocket URL for a companion's live chat channel, carrying the token. */
export function chatSocketUrl(agentId, token) {
  const base = WS_BASE
    ? `${WS_BASE}/ws/chat/${encodeURIComponent(agentId)}`
    : `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${
        window.location.host
      }/ws/chat/${encodeURIComponent(agentId)}`;
  const authToken = token ?? getToken();
  return authToken ? `${base}?token=${encodeURIComponent(authToken)}` : base;
}

export const api = {
  health: (signal) => request("/api/health", { signal }),

  personas: (signal) => request("/api/personas", { signal }),

  // --- Accounts ---------------------------------------------------------- //
  signup: (payload, signal) =>
    request("/api/auth/signup", { method: "POST", body: payload, signal }),

  login: (payload, signal) =>
    request("/api/auth/login", { method: "POST", body: payload, signal }),

  logout: () => request("/api/auth/logout", { method: "POST" }),

  me: (signal) => request("/api/auth/me", { signal }),

  updateMe: (payload, signal) =>
    request("/api/auth/me", { method: "PATCH", body: payload, signal }),

  // --- Companions -------------------------------------------------------- //
  nameSuggestions: (personaId, count = 3, signal) =>
    request(`/api/personas/${personaId}/names?count=${count}`, { signal }),

  listAgents: (signal) => request("/api/agents", { signal }),

  createAgent: (payload, signal) =>
    request("/api/agents", { method: "POST", body: payload, signal }),

  getAgent: (agentId, signal) => request(`/api/agents/${agentId}`, { signal }),

  updateAgent: (agentId, payload, signal) =>
    request(`/api/agents/${agentId}`, { method: "PATCH", body: payload, signal }),

  deleteAgent: (agentId) => request(`/api/agents/${agentId}`, { method: "DELETE" }),

  messages: (agentId, { limit = 200, before } = {}, signal) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (before) params.set("before", String(before));
    return request(`/api/agents/${agentId}/messages?${params}`, { signal });
  },

  clearMessages: (agentId) =>
    request(`/api/agents/${agentId}/messages`, { method: "DELETE" }),

  starters: (agentId, signal) =>
    request(`/api/agents/${agentId}/starters`, { signal }),
};
