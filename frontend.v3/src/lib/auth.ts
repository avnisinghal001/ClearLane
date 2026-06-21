// Simple demo auth. Citizen is open (no credentials). Police-station + government
// authenticate via POST /api/auth/login, falling back to offline credentials
// validated against the bundled station list (offline-first contract).
import { getStations } from "./api";
import type { AuthSession, Role } from "./types";

const BASE = (import.meta.env.VITE_API_BASE || "").replace(/\/$/, "");
const KEY = "cl_v3_auth";

export function slugify(name: string): string {
  return (name || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "station";
}

export function getAuth(): AuthSession | null {
  try {
    return JSON.parse(localStorage.getItem(KEY) || "null");
  } catch {
    return null;
  }
}

function setAuth(a: AuthSession | null) {
  if (a) localStorage.setItem(KEY, JSON.stringify(a));
  else localStorage.removeItem(KEY);
}

export const currentRole = (): Role | null => getAuth()?.role ?? null;

// Citizen: open access, no credentials.
export function enterCitizen(): AuthSession {
  const a: AuthSession = { token: "citizen", role: "citizen", scope: "open", name: "Citizen", live: false };
  setAuth(a);
  return a;
}

let _slugMap: Record<string, { name: string; slug: string }> | null = null;
async function stationSlugMap() {
  if (_slugMap) return _slugMap;
  const list = await getStations();
  _slugMap = {};
  for (const s of list) {
    if (s.station) _slugMap[s.slug || slugify(s.station)] = { name: s.station, slug: s.slug || slugify(s.station) };
  }
  return _slugMap;
}

export async function login(role: "govt" | "station", username: string, password: string): Promise<AuthSession> {
  const user = (username || "").trim().toLowerCase();
  const pw = (password || "").trim().toLowerCase();
  // 1) live backend
  try {
    const r = await fetch(BASE + "/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: user, password: pw }),
    });
    if (r.ok) {
      const data = await r.json();
      const a: AuthSession = {
        token: data.token,
        role: data.role === "govt" ? "govt" : "station",
        scope: data.scope ?? (data.role === "govt" ? "all" : user),
        name: data.name ?? (data.role === "govt" ? "Government Command" : user),
        live: true,
      };
      setAuth(a);
      return a;
    }
    if (r.status === 401) throw new Error("Invalid credentials.");
  } catch (e) {
    if (e instanceof Error && e.message.includes("Invalid")) throw e;
    // network error -> offline auth
  }
  // 2) offline auth (slug == username == password)
  if (role === "govt") {
    if (user === "govt" && pw === "govt") {
      const a: AuthSession = { token: "offline-govt", role: "govt", scope: "all", name: "Government Command", live: false };
      setAuth(a);
      return a;
    }
    throw new Error("Invalid credentials. Try govt / govt.");
  }
  const map = await stationSlugMap();
  if (map[user] && pw === user) {
    const a: AuthSession = { token: "offline-" + user, role: "station", scope: user, name: map[user].name, live: false };
    setAuth(a);
    return a;
  }
  throw new Error("Invalid credentials. Use <station-slug> / <station-slug>.");
}

export async function logout() {
  const a = getAuth();
  if (a?.token && !a.token.startsWith("offline") && a.token !== "citizen") {
    try {
      await fetch(BASE + "/api/auth/logout", {
        method: "POST",
        headers: { Authorization: `Bearer ${a.token}` },
      });
    } catch {
      /* ignore */
    }
  }
  setAuth(null);
}
