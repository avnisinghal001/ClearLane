// RBAC auth layer for the Force Command system.
//  * Government super-admin:  govt / govt          -> role "govt",  scope "all"
//  * Per-station command:     <slug> / <slug>      -> role "station", scope slug
// Token sessions live in the backend (force.py). When the backend is unreachable
// we fall back to OFFLINE auth validated against the bundled station list so the
// judging demo always works (same offline-first contract as the rest of the app).
import { api } from "./api.js";

const BASE = (import.meta.env.VITE_API_BASE || "").replace(/\/$/, "");
const KEY = "cl_auth";

export function slugify(name) {
  return (name || "").toLowerCase().replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "") || "station";
}

export function getAuth() {
  try { return JSON.parse(localStorage.getItem(KEY) || "null"); }
  catch { return null; }
}
function setAuth(a) {
  if (a) localStorage.setItem(KEY, JSON.stringify(a));
  else localStorage.removeItem(KEY);
}
export const isGovt = () => getAuth()?.role === "govt";
export const scopeSlug = () => getAuth()?.scope;

export function authHeader() {
  const a = getAuth();
  return a?.token ? { Authorization: `Bearer ${a.token}` } : {};
}

// Resolve the canonical slug list from the bundled / live station list.
let _slugMap = null;
async function stationSlugMap() {
  if (_slugMap) return _slugMap;
  const list = await api("/api/stations");
  _slugMap = {};
  (list || []).forEach((s) => {
    if (s.station && s.station !== "No Police Station")
      _slugMap[slugify(s.station)] = { name: s.station, lat: s.lat, lon: s.lon };
  });
  return _slugMap;
}

export async function login(username, password) {
  const user = (username || "").trim().toLowerCase();
  const pw = (password || "").trim().toLowerCase();
  // 1) try the live backend (relative "/api" on Vercel, or an absolute base)
  try {
    const r = await fetch(BASE + "/api/auth/login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: user, password: pw }),
    });
    if (r.ok) {
      const a = { ...(await r.json()), live: true };
      setAuth(a);
      return a;
    }
    if (r.status === 401) throw new Error("Invalid credentials.");
  } catch (e) {
    if (String(e.message).includes("Invalid")) throw e;
    // network error / no backend -> fall through to offline auth
  }
  // 2) offline auth (slug == username == password)
  if (user === "govt" && pw === "govt") {
    const a = { token: "offline-govt", role: "govt", scope: "all",
                name: "Government Command", live: false };
    setAuth(a);
    return a;
  }
  const map = await stationSlugMap();
  if (map[user] && pw === user) {
    const a = { token: "offline-" + user, role: "station", scope: user,
                name: map[user].name, live: false };
    setAuth(a);
    return a;
  }
  throw new Error("Invalid credentials.");
}

export async function logout() {
  const a = getAuth();
  if (a?.token && !a.token.startsWith("offline")) {
    try {
      await fetch(BASE + "/api/auth/logout", {
        method: "POST", headers: authHeader(),
      });
    } catch { /* ignore */ }
  }
  setAuth(null);
}

// Authenticated fetch helper for force endpoints (returns null on failure so the
// caller can fall back to the offline force engine). Uses the same-origin "/api"
// on Vercel; an offline token short-circuits straight to the offline engine.
export async function authFetch(path, opts = {}) {
  const a = getAuth();
  if (!a || a.token?.startsWith("offline")) return null;
  try {
    const r = await fetch(BASE + path, {
      ...opts,
      headers: { "Content-Type": "application/json", ...authHeader(), ...(opts.headers || {}) },
    });
    if (!r.ok) {
      if (r.status === 401) { setAuth(null); location.reload(); }
      return null;
    }
    return await r.json();
  } catch { return null; }
}
