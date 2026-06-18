// API layer. Every call falls back to the bundled /demo/*.json so the dashboard
// always renders even when the backend is asleep or unreachable (judging safety).
const BASE = (import.meta.env.VITE_API_BASE || "").replace(/\/$/, "");

const DEMO = {
  "/api/map/payload": "/demo/map_payload.json",
  "/api/coverage-curve": "/demo/coverage_curve.json",
  "/api/timing-gap": "/demo/timing_gap.json",
  "/api/emerging": "/demo/emerging.json",
  "/api/forecast": "/demo/forecast.json",
  "/api/typology": "/demo/typology.json",
  "/api/stations": "/demo/stations.json",
  "/api/validation": "/demo/validation.json",
  "/api/evidence-points": "/demo/evidence_points.json",
  "/api/replay-frames": "/demo/replay_frames.json",
  "/api/offenders": "/demo/offenders.json",
};

let LIVE = !!BASE;
export const isLive = () => LIVE;

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status}`);
  return r.json();
}

// Demo-only artifacts loaded directly (zone detail, briefings, timing blind spots).
let _detail = null;
async function detailMap() {
  if (!_detail) _detail = await getJSON("/demo/zones_detail.json");
  return _detail;
}

export async function api(path) {
  if (BASE) {
    try {
      return await getJSON(BASE + path);
    } catch (e) {
      LIVE = false; // fall through to demo
    }
  }
  // demo fallbacks
  if (path.startsWith("/api/zone/")) {
    const id = decodeURIComponent(path.split("/api/zone/")[1]);
    return (await detailMap())[id] || null;
  }
  if (path.startsWith("/api/priority/queue")) {
    const p = await getJSON("/demo/map_payload.json");
    return [...p.zones].sort((a, b) => a.rank - b.rank);
  }
  if (path.startsWith("/api/flow-impact")) {
    const p = await getJSON("/demo/map_payload.json");
    return [...p.zones].sort(
      (a, b) => (a.flow_impact_rank ?? 1e9) - (b.flow_impact_rank ?? 1e9));
  }
  if (path === "/api/timing-gap") {
    const t = await getJSON("/demo/timing_gap.json");
    const p = await getJSON("/demo/map_payload.json");
    return { timing: t, blind_spots: p.zones.filter((z) => z.evening_blind_spot) };
  }
  if (path === "/api/validation") {
    const v = await getJSON("/demo/validation.json");
    let offender = null;
    try { offender = await getJSON("/demo/offender_stat.json"); } catch {}
    return { validation: v, offender_stat: offender };
  }
  if (path.startsWith("/api/search")) {
    const q = decodeURIComponent((path.split("q=")[1] || "")).toLowerCase();
    const idx = await getJSON("/demo/search_index.json");
    return idx.filter((r) =>
      (r.label || "").toLowerCase().includes(q) ||
      (r.station || "").toLowerCase().includes(q) ||
      (r.junction || "").toLowerCase().includes(q) ||
      r.id.toLowerCase().includes(q)).slice(0, 25);
  }
  const key = path.split("?")[0];
  if (DEMO[key]) return getJSON(DEMO[key]);
  throw new Error("no demo fallback for " + path);
}

// ---- Operational loop (live backend, with an offline in-memory fallback) ---
import * as localOps from "./localOps.js";

async function postJSON(path, body) {
  const r = await fetch(BASE + path, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    let detail = `${r.status}`;
    try { detail = (await r.json()).detail || detail; } catch {}
    throw new Error(detail);
  }
  return r.json();
}

export const opSnapshot = async () => {
  if (BASE) { try { return await getJSON(BASE + "/api/operational/snapshot"); } catch {} }
  return localOps.snapshot();
};
export const opComplaint = async (body) => {
  if (BASE) { try { return await postJSON("/api/complaints", body); } catch (e) {
    if (String(e.message).includes("bounding box")) throw e; } }
  return localOps.postComplaint(body);
};
export const opDispatch = async (body) => {
  if (BASE) { try { return await postJSON("/api/dispatches", body); } catch {} }
  return localOps.postDispatch(body);
};
export const opFeedback = async (body) => {
  if (BASE) { try { return await postJSON("/api/officer-feedback", body); } catch {} }
  return localOps.postFeedback(body);
};
export const opPatchStatus = async (id, stateVal) => {
  if (BASE) { try {
    const r = await fetch(`${BASE}/api/dispatches/${id}/status`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ state: stateVal }) });
    if (r.ok) return r.json();
  } catch {} }
  return localOps.patchStatus(id, stateVal);
};
// seed the offline fallback's zone index from the bundled map payload
export const seedOpZones = (zones) =>
  localOps.setZones((zones || []).map((z) => ({
    id: z.id, name: z.name, lat: z.lat, lon: z.lon, tier: z.tier, priority: z.priority })));

export async function copilot(body) {
  if (BASE) {
    try {
      const r = await fetch(BASE + "/api/copilot", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (r.ok) return r.json();
    } catch {}
  }
  // demo briefing fallback
  try {
    const briefs = await getJSON("/demo/briefings.json");
    const b = body.station && briefs[body.station];
    return { answer: b || "Copilot is a deployment extension; run the backend to enable it.",
             source: "deterministic" };
  } catch {
    return { answer: "Copilot unavailable in offline demo.", source: "none" };
  }
}
