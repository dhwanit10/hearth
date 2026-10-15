/**
 * REST client.
 *
 * By default every call goes to the same origin, which the Vite dev server
 * proxies to FastAPI (see vite.config.js). Set VITE_API_BASE to point the UI at
 * a backend on another host.
 */

const API_BASE = (import.meta.env?.VITE_API_BASE ?? "").replace(/\/+$/, "");
const WS_BASE = (import.meta.env?.VITE_WS_BASE ?? "").replace(/\/+$/, "");

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "ApiError";
    this.status = status;
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
  return fallback;
}

async function request(path, { method = "GET", body, signal } = {}) {
  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      signal,
      headers: body ? { "Content-Type": "application/json" } : undefined,
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
    );
  }

  if (response.status === 204) return null;
  return response.json();
}

/** Websocket URL for a companion's live chat channel. */
export function chatSocketUrl(agentId) {
  if (WS_BASE) return `${WS_BASE}/ws/chat/${encodeURIComponent(agentId)}`;
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/chat/${encodeURIComponent(agentId)}`;
}

export const api = {
  health: (signal) => request("/api/health", { signal }),

  personas: (signal) => request("/api/personas", { signal }),

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
