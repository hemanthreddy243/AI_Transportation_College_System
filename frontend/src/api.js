const TOKEN_KEY = "smartbus_token";

export const auth = {
  get token() {
    try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
  },
  set(token) {
    try { localStorage.setItem(TOKEN_KEY, token); } catch { /* storage blocked */ }
  },
  clear() {
    try { localStorage.removeItem(TOKEN_KEY); } catch { /* storage blocked */ }
  },
};

export async function api(path, { method = "GET", body } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth.token) headers.Authorization = `Bearer ${auth.token}`;
  const res = await fetch(`/api${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && auth.token) {
    auth.clear();
    window.location.href = "/login";
  }
  if (!res.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail.map((d) => d.msg).join(", ")
      : data.detail;
    throw new Error(detail || `Request failed (${res.status})`);
  }
  return data;
}

export function fmtDateTime(iso) {
  if (!iso) return "";
  return new Date(iso).toLocaleString(undefined, {
    weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit",
  });
}

export function fmtDate(iso) {
  return new Date(iso + "T00:00").toLocaleDateString(undefined, {
    weekday: "long", day: "numeric", month: "long",
  });
}

export function timeAgo(iso) {
  if (!iso) return "";
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.max(s, 0)}s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  return fmtDateTime(iso);
}
