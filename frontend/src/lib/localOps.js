// Offline-first fallback for the operational loop. Mirrors backend/app/operational.py
// rules in-memory so the closed-loop demo works even with NO backend and NO internet.
// HONESTY: never touches historical scores — only computes a separate live_adjustment.
const OP_RULES = {
  complaint_unverified: 5, verified_obstruction: 12, needs_towing: 15,
  action_taken: -8, false_alarm: -10, max_adjustment: 40,
};
const BBOX = { lat_min: 12.8, lat_max: 13.29, lon_min: 77.44, lon_max: 77.77 };

let ZONES = [];               // [{id,name,lat,lon,tier,priority}]
const state = new Map();      // zone_id -> {boost,dispatch_state,escalated,complaints}
let complaints = [];
let dispatches = [];
let seqC = 0, seqD = 0;

export function setZones(zones) {
  if (zones && zones.length && !ZONES.length) ZONES = zones;
}
function haversine(a, b, c, d) {
  const R = 6371000, r = Math.PI / 180;
  const dphi = (c - a) * r, dl = (d - b) * r;
  const x = Math.sin(dphi / 2) ** 2 + Math.cos(a * r) * Math.cos(c * r) * Math.sin(dl / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(x));
}
function nearest(lat, lon, maxM = 600) {
  let best = null, bd = Infinity;
  for (const z of ZONES) { const dd = haversine(lat, lon, z.lat, z.lon); if (dd < bd) { bd = dd; best = z; } }
  return bd <= maxM ? { zone: best, d: bd } : { zone: null, d: bd };
}
function st(id) {
  if (!state.has(id)) state.set(id, { boost: 0, dispatch_state: null, escalated: false, complaints: 0 });
  return state.get(id);
}
const clamp = (x) => Math.max(0, Math.min(OP_RULES.max_adjustment, x));

export const inBbox = (lat, lon) =>
  lat >= BBOX.lat_min && lat <= BBOX.lat_max && lon >= BBOX.lon_min && lon <= BBOX.lon_max;

export function snapshot() {
  const idx = Object.fromEntries(ZONES.map((z) => [z.id, z]));
  const zones = [];
  for (const [id, s] of state) {
    if (s.boost <= 0 && !s.dispatch_state && !s.escalated) continue;
    const z = idx[id]; const hist = z ? z.priority : 0;
    zones.push({
      zone_id: id, name: z ? z.name : id, lat: z?.lat, lon: z?.lon, tier: z?.tier,
      historical_priority: +hist.toFixed(1), live_adjustment: +s.boost.toFixed(1),
      operational_priority: +Math.min(100, hist + s.boost).toFixed(1),
      dispatch_state: s.dispatch_state, escalated: s.escalated, complaints: s.complaints,
    });
  }
  zones.sort((a, b) => b.operational_priority - a.operational_priority);
  return {
    ts: Date.now() / 1000, offline: true,
    counts: {
      active_complaints: complaints.length,
      open_dispatches: dispatches.filter((d) => !["cleared", "structural_escalation"].includes(d.state)).length,
      live_zones: zones.length, escalations: zones.filter((z) => z.escalated).length,
    },
    zones, complaints: [...complaints].reverse(), dispatches: [...dispatches].reverse(),
  };
}

export function postComplaint({ lat, lon, description = "", vehicle_type = "" }) {
  if (!inBbox(lat, lon)) throw new Error("Coordinate outside the Bengaluru bounding box.");
  const { zone, d } = nearest(lat, lon);
  const c = { id: ++seqC, lat, lon, description, vehicle_type, zone_id: zone?.id || null,
    distance_m: zone ? +d.toFixed(1) : null, status: "unverified", created_ts: Date.now() / 1000 };
  complaints.push(c);
  if (zone) { const s = st(zone.id); s.boost = clamp(s.boost + OP_RULES.complaint_unverified); s.complaints++; }
  return { id: c.id, zone_id: zone?.id || null, zone_name: zone?.name || null,
    assignment: zone ? "nearest_historical_zone" : "emerging_operational_point",
    distance_m: c.distance_m, status: "unverified" };
}

export function postDispatch({ zone_id, complaint_id = null, state: stt = "assigned" }) {
  const d = { id: ++seqD, zone_id, complaint_id, state: stt, updated_ts: Date.now() / 1000 };
  dispatches.push(d); st(zone_id).dispatch_state = stt;
  return { id: d.id, zone_id, state: stt };
}

export function postFeedback({ zone_id, kind, dispatch_id = null }) {
  const s = st(zone_id);
  let newState = s.dispatch_state;
  if (kind === "verified_obstruction") { s.boost = clamp(s.boost + OP_RULES.verified_obstruction); newState = "on_site"; }
  else if (kind === "needs_towing") { s.boost = clamp(s.boost + OP_RULES.needs_towing); newState = "on_site"; }
  else if (kind === "action_taken") { s.boost = clamp(s.boost + OP_RULES.action_taken); newState = "action_taken"; }
  else if (kind === "cleared") { s.boost = 0; newState = "cleared"; }
  else if (kind === "false_alarm" || kind === "no_obstruction" || kind === "no_obstruction_found") { s.boost = clamp(s.boost + OP_RULES.false_alarm); newState = "cleared"; }
  else if (kind === "structural_issue") { s.escalated = true; newState = "structural_escalation"; }
  s.dispatch_state = newState;
  if (dispatch_id) { const d = dispatches.find((x) => x.id === dispatch_id); if (d) { d.state = newState; d.updated_ts = Date.now() / 1000; } }
  return { stored: true, zone_id, kind, new_state: newState };
}

export function patchStatus(dispatch_id, stt) {
  const d = dispatches.find((x) => x.id === dispatch_id);
  if (d) { d.state = stt; d.updated_ts = Date.now() / 1000;
    const s = st(d.zone_id);
    if (stt === "cleared") { s.boost = 0; s.dispatch_state = "cleared"; }
    else if (stt === "structural_escalation") { s.escalated = true; s.dispatch_state = stt; }
    else s.dispatch_state = stt;
  }
  return { id: dispatch_id, state: stt };
}
