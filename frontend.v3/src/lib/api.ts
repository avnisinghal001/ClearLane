// Offline-first API client for the /api/v3 contract. Every read tries the live
// backend first (relative "/api" on Vercel, Vite proxy in dev, or an absolute
// VITE_API_BASE), and on ANY failure falls back to the bundled /demo-v3/*.json
// so the app always renders (judging safety). Writes try the backend, then fall
// back to the in-memory localStore mirror.
import "./time";
import * as local from "./localStore";
import { composeQueue } from "./rerank";
import { genRoster, RANK_ABBR, RANKS, SHIFT_ORDER, SHIFTS } from "./force";
import type {
  AutoAllocation,
  Cell,
  ComplaintInput,
  DispatchPlan,
  DispatchQueue,
  ForceMeta,
  Kpis,
  MapPayload,
  Officer,
  ResolveInput,
  RosterPayload,
  RosterSummary,
  Station,
  Ticket,
  TicketInput,
  When,
} from "./types";

const BASE = (import.meta.env.VITE_API_BASE || "").replace(/\/$/, "");

let LIVE = true;
const liveListeners = new Set<(live: boolean) => void>();
export const isLive = () => LIVE;
export function onLiveChange(cb: (live: boolean) => void) {
  liveListeners.add(cb);
  return () => {
    liveListeners.delete(cb);
  };
}
function setLive(v: boolean) {
  if (LIVE !== v) {
    LIVE = v;
    liveListeners.forEach((cb) => cb(v));
  }
}

async function getJSON<T>(url: string, opts?: RequestInit): Promise<T> {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error(String(r.status));
  return (await r.json()) as T;
}

// ---- demo bundle (lazy, cached) ------------------------------------------
const _cache = new Map<string, unknown>();
async function demo<T>(file: string): Promise<T> {
  if (!_cache.has(file)) _cache.set(file, await getJSON<T>(`/demo-v3/${file}`));
  return _cache.get(file) as T;
}

interface DemoCells {
  cells: Cell[];
  hour_profile: number[];
  dow_order: string[];
  congestion_mode: string;
}

async function tryLive<T>(path: string, opts?: RequestInit): Promise<T | null> {
  if (!LIVE) return null;
  try {
    return await getJSON<T>(BASE + path, opts);
  } catch {
    setLive(false);
    return null;
  }
}

// --------------------------------------------------------------------------
export interface AppConfig {
  mappls_key: string | null; // REST key — engine 1 (map_load)
  static_key?: string | null; // static/JS key — engine 2 (Mappls v3 access_token)
  demo?: boolean;
}

export async function getConfig(): Promise<AppConfig> {
  try {
    return await getJSON<AppConfig>(BASE + "/api/config");
  } catch {
    return demo<AppConfig>("config.json");
  }
}

function round(x: number, d = 1) {
  const k = 10 ** d;
  return Math.round(x * k) / k;
}

// Hourly congestion overlay (mirror of the backend; modeled typical, not measured).
interface DemoHourlyCongestion {
  provenance: string;
  curves: Record<string, number[]>;
  global: number[];
}
const HC_BASE_W = 0.4;
const HC_CONG_W = 0.6;
// MODELED day-of-week congestion factor (mirror of ml.v3 SIM_DOW_FACTORS +
// api._dow_factor) so the offline display_score varies by DAY as well as hour.
const DOW_FACTORS: Record<string, number> = {
  Mon: 0.9, Tue: 0.96, Wed: 1.0, Thu: 1.01, Fri: 1.06, Sat: 1.09, Sun: 1.14,
};
// REAL day-shaped congestion (mirror of api/clearlane/v3.py SIM_DAYHOUR): each day
// has its OWN 24-hour SHAPE so scrubbing the day re-patterns the offline map too
// (Sun 09:00 quiet vs Mon 09:00 rush; Mon 12:00 dip vs Sun 12:00 busy).
const SIM_DAYHOUR: Record<string, number[]> = {
  Mon: [0.26, 0.22, 0.2, 0.2, 0.24, 0.34, 0.52, 0.74, 0.92, 0.95, 0.84, 0.66, 0.58, 0.55, 0.56, 0.62, 0.78, 0.94, 1.0, 0.96, 0.8, 0.6, 0.4, 0.3],
  Tue: [0.27, 0.23, 0.21, 0.21, 0.25, 0.36, 0.55, 0.78, 0.96, 1.0, 0.88, 0.68, 0.6, 0.57, 0.58, 0.64, 0.8, 0.98, 1.04, 0.99, 0.82, 0.62, 0.42, 0.31],
  Wed: [0.27, 0.23, 0.21, 0.21, 0.25, 0.36, 0.55, 0.78, 0.96, 1.0, 0.88, 0.68, 0.6, 0.57, 0.58, 0.64, 0.8, 0.98, 1.04, 0.99, 0.82, 0.62, 0.42, 0.31],
  Thu: [0.28, 0.24, 0.22, 0.22, 0.26, 0.37, 0.56, 0.79, 0.97, 1.01, 0.89, 0.69, 0.61, 0.58, 0.59, 0.66, 0.82, 1.0, 1.05, 1.0, 0.84, 0.64, 0.44, 0.32],
  Fri: [0.3, 0.25, 0.22, 0.22, 0.26, 0.37, 0.56, 0.8, 0.97, 1.0, 0.9, 0.72, 0.66, 0.64, 0.66, 0.74, 0.88, 1.02, 1.08, 1.06, 0.96, 0.8, 0.58, 0.42],
  Sat: [0.4, 0.32, 0.27, 0.24, 0.24, 0.28, 0.36, 0.48, 0.62, 0.74, 0.84, 0.9, 0.92, 0.9, 0.9, 0.94, 1.0, 1.04, 1.06, 1.04, 0.98, 0.88, 0.74, 0.56],
  Sun: [0.42, 0.34, 0.28, 0.25, 0.24, 0.26, 0.3, 0.38, 0.5, 0.64, 0.8, 0.92, 0.98, 0.96, 0.88, 0.84, 0.86, 0.92, 1.0, 1.04, 1.0, 0.9, 0.74, 0.56],
};
const HC_AMP: Record<string, number> = { ring_road: 1.0, arterial: 0.95, commercial: 0.9, main_road: 0.85, local: 0.45, unknown: 0.7 };
function dayCong(roadClass: string | null | undefined, dowLabel: string, hour: number): number {
  const shape = SIM_DAYHOUR[dowLabel] || SIM_DAYHOUR.Wed;
  const base = shape[((hour % 24) + 24) % 24];
  const amp = HC_AMP[roadClass || "unknown"] ?? 0.7;
  return Math.max(0, Math.min(1, 0.08 + base * (0.45 + 0.55 * amp)));
}
const clamp100 = (x: number) => Math.max(0, Math.min(100, x));
const LIFT_W = 0.5;
const DOW_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

// JS getDay (0=Sun..6=Sat) -> Mon..Sun index (0=Mon..6=Sun), matching dow_curve.
function dowIndexFor(when: When, date?: string): number {
  const d = new Date();
  if (when === "tomorrow") d.setDate(d.getDate() + 1);
  if (when === "custom" && date) {
    const cd = new Date(date + "T00:00:00");
    if (!Number.isNaN(cd.getTime())) return (cd.getDay() + 6) % 7;
  }
  return (d.getDay() + 6) % 7;
}

// Offline learning lift (approx): demo cells expose drift_z on emerging cells, so
// the offline fallback bends those; the live backend bends all ~860 online cells.
function offlineLift(c: Cell): number {
  const z = c.drift_z;
  if (z == null) return 0;
  return Math.max(-0.5, Math.min(1.5, z / 3));
}

// Compose the /api/v3/map payload offline. Mirrors the backend's four lenses:
// now/today/tomorrow are LEARNING-ADJUSTED; custom is HISTORICAL-ONLY.
function composeMap(when: When, hour: number | null, date: string | undefined, base: DemoCells, kpis: Kpis, hc: DemoHourlyCongestion | null): MapPayload {
  const learning = when !== "custom";
  const dowBase = when !== "now"; // today/tomorrow/custom use the forecast curve
  const dow = dowIndexFor(when, date);
  const hr = hour ?? new Date().getHours();

  let maxBase = 1;
  const baseVal = new Map<string, number>();
  if (dowBase) {
    for (const c of base.cells) {
      const v = c.dow_curve ? c.dow_curve[dow] ?? 0 : (c.weekly_expected ?? 0) / 7 || c.intensity * 0.3;
      baseVal.set(c.h3_r10, v);
      if (v > maxBase) maxBase = v;
    }
  }

  const dowL = DOW_LABELS[dow];
  void DOW_FACTORS; // superseded by SIM_DAYHOUR (kept for reference)
  let nAdjusted = 0;
  let nEmerging = 0;
  const cells: Cell[] = base.cells.map((c) => {
    const adj = local.liveAdjustment(c.h3_r10);
    const op = clamp100(c.pic_score + adj);
    const cong = dayCong(c.road_class, dowL, hr); // DAY-shaped congestion (not scaled)
    const mod = HC_BASE_W + HC_CONG_W * cong;
    const lift = learning ? offlineLift(c) : 0;
    if (Math.abs(lift) >= 0.08) nAdjusted++;
    if (c.emerging) nEmerging++;
    const baseProp = dowBase ? ((baseVal.get(c.h3_r10) ?? 0) / maxBase) * 100 : c.pic_score;
    const baseL = baseProp * (1 + LIFT_W * lift);
    let intensity = round(clamp100(baseL * mod), 1);
    if (when === "now") intensity = round(clamp100(intensity + 0.5 * adj), 1);
    // pure TIME-VARYING composite: pic_score × DAY-shaped congestion for (dow,hour) —
    // recolours AND re-patterns per day as you scrub. MODELED, never measured.
    const displayScore = round(clamp100(c.pic_score * mod), 1);
    return {
      ...c,
      intensity,
      display_score: displayScore,
      pressure: c.pic_score,
      forecast_intensity: when === "now" ? null : round(clamp100(baseL * mod), 1),
      congestion_hour: round(cong, 3),
      learn_lift: round(lift, 3),
      live_adjustment: round(adj, 1),
      operational_priority: round(op, 1),
    };
  });

  const hh = `${String(hr).padStart(2, "0")}:00`;
  let source_note: string;
  let badge: string;
  if (when === "now") {
    source_note = `Now @ ${hh} — live PIC, learning-adjusted across ${nAdjusted} zones (+${nEmerging} emerging), × modeled typical congestion, + live reports.`;
    badge = `Now · ${hh} · learning-adjusted`;
  } else if (when === "today" || when === "tomorrow") {
    source_note = `${when[0].toUpperCase()}${when.slice(1)} (${dowL}) @ ${hh} — day-of-week propensity ADJUSTED by the self-learning loop across ${nAdjusted} zones, × modeled typical congestion.`;
    badge = `${when[0].toUpperCase()}${when.slice(1)} · ${dowL} · ${hh} · learning-adjusted`;
  } else {
    source_note = `${date ?? ""} (${dowL}) @ ${hh} — HISTORICAL day-of-week propensity × modeled typical congestion. No learning, no live reports — a rough-idea view for other days.`;
    badge = `${date ?? ""} · ${dowL} · ${hh} · historical only (rough idea)`;
  }

  return {
    when,
    hour: hr,
    date: when === "custom" ? date : null,
    dow: dowL,
    source: when === "now" ? "live" : "forecast",
    learning_adjusted: learning,
    n_emerging: nEmerging,
    n_adjusted: nAdjusted,
    congestion_source: "simulated",
    congestion_live: false,
    congestion_dow: dowL,
    source_note: source_note + " Congestion is a SIMULATED time/day model, not measured from tickets.",
    badge,
    cells,
    kpis,
    hour_profile: hc?.global ?? base.hour_profile,
    dow_order: base.dow_order,
  };
}

// Client-side WHOLE-MAP cache: scrubbing back to a (day, hour) already fetched is
// instant (no network). `now` is short-lived (live data); other lenses are stable
// until the page reloads or forceRecompute() clears the cache.
const _mapCache = new Map<string, { ts: number; payload: MapPayload }>();
const MAP_TTL_NOW_MS = 20_000;
export function clearMapCache() {
  _mapCache.clear();
}

export async function getMap(when: When, hour: number | null, date?: string, force = false): Promise<MapPayload> {
  const lens = `${when}:${hour ?? "_"}:${when === "custom" ? date ?? "" : ""}`;
  const hit = _mapCache.get(lens);
  // `force` (e.g. the "Now" button) always hits the API for fresh live state.
  if (!force && hit && (when !== "now" || Date.now() - hit.ts < MAP_TTL_NOW_MS)) {
    return { ...hit.payload, served_from_client_cache: true } as MapPayload;
  }

  const qs = new URLSearchParams({ when });
  if (hour != null) qs.set("hour", String(hour)); // hour drives the heatmap in every mode
  if (when === "custom" && date) qs.set("date", date);
  // Dense map like v1 (~1.5k zones): ask for the full representative spread (head +
  // stride across all 6.5k occupied cells) instead of the thin 250-cell default.
  qs.set("limit", "2000");
  const live = await tryLive<MapPayload>(`/api/v3/map?${qs}`);
  let out: MapPayload;
  if (live && live.cells) {
    out = {
      ...live,
      when,
      hour: live.hour ?? hour,
      source: when === "now" ? "live" : "forecast",
      source_note: live.source_note ?? "",
    };
  } else {
    const [base, kpis, hc] = await Promise.all([
      demo<DemoCells>("cells.json"),
      demo<Kpis>("kpis.json"),
      demo<DemoHourlyCongestion>("hourly_congestion.json").catch(() => null),
    ]);
    local.seed(base.cells, await demo<Ticket[]>("tickets.json"));
    out = composeMap(when, hour, date, base, kpis, hc);
  }
  _mapCache.set(lens, { ts: Date.now(), payload: out });
  return out;
}

// Government-only FORCE update: recompute online rates + re-rank + re-bake the
// 24-hour heatmap cache. Needs the live API + a government bearer session.
export async function forceRecompute(): Promise<{
  ok: boolean;
  error?: string;
  heatmap?: { n_cells: number; provenance: string; generated_at: string };
  recompute?: Record<string, unknown>;
}> {
  let token: string | null = null;
  try {
    token = JSON.parse(localStorage.getItem("cl_v3_auth") || "null")?.token ?? null;
  } catch {
    token = null;
  }
  try {
    const r = await fetch(BASE + "/api/v3/recompute", {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!r.ok) {
      return {
        ok: false,
        error:
          r.status === 401 || r.status === 403
            ? "Government login required to force a recompute."
            : r.status === 503
              ? "Recompute needs the live backend + MongoDB (offline demo can't recompute)."
              : `Recompute failed (${r.status}).`,
      };
    }
    clearMapCache(); // fresh recompute -> drop the client map cache so scrubs refetch
    return await r.json();
  } catch {
    return { ok: false, error: "Backend unavailable — recompute needs the live API + MongoDB." };
  }
}

export async function getKpis(): Promise<Kpis> {
  return demo<Kpis>("kpis.json");
}

export async function getStations(): Promise<Station[]> {
  const live = await tryLive<Station[]>("/api/v3/stations");
  return live ?? demo<Station[]>("stations.json");
}

// ---- Government station management (force layer; needs a govt bearer + Mongo) ----
export interface GovtStation {
  slug: string;
  name: string;
  lat: number | null;
  lon: number | null;
  n_zones: number;
  officers: number;
  active: boolean;
}

function authHeader(): Record<string, string> {
  try {
    const t = JSON.parse(localStorage.getItem("cl_v3_auth") || "null")?.token;
    return t && !String(t).startsWith("offline") && t !== "citizen" ? { Authorization: `Bearer ${t}` } : {};
  } catch {
    return {};
  }
}

export async function getGovtStations(): Promise<{ stations: GovtStation[]; totals: { stations: number; officers: number } } | null> {
  try {
    const r = await fetch(BASE + "/api/govt/stations", { headers: authHeader() });
    if (!r.ok) return null;
    return await r.json();
  } catch {
    return null;
  }
}

export interface AddStationResult {
  ok: boolean;
  error?: string;
  slug?: string;
  inspector?: { id: number; name: string; badge: string; rank: string; shift: string };
  officers?: number;
}

export async function addGovtStation(name: string, lat: number, lon: number, inspectorName?: string): Promise<AddStationResult> {
  try {
    const r = await fetch(BASE + "/api/govt/stations", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeader() },
      body: JSON.stringify({ name, lat, lon, inspector_name: inspectorName || "" }),
    });
    if (r.ok) {
      const j = await r.json();
      return { ok: true, slug: j.slug, inspector: j.inspector, officers: j.officers };
    }
    if (r.status === 401 || r.status === 403) return { ok: false, error: "Government login required to manage stations." };
    if (r.status === 409) return { ok: false, error: "A station with that name already exists." };
    if (r.status === 503) return { ok: false, error: "Station management needs the live backend + MongoDB." };
    return { ok: false, error: `Add failed (${r.status}).` };
  } catch {
    return { ok: false, error: "Backend unavailable — station management needs the live API + MongoDB." };
  }
}

export async function removeGovtStation(slug: string): Promise<{ ok: boolean; error?: string }> {
  try {
    const r = await fetch(`${BASE}/api/govt/stations/${encodeURIComponent(slug)}`, { method: "DELETE", headers: authHeader() });
    if (r.ok) return { ok: true };
    if (r.status === 401 || r.status === 403) return { ok: false, error: "Government login required." };
    if (r.status === 404) return { ok: false, error: "Station not found." };
    if (r.status === 503) return { ok: false, error: "Station management needs the live backend + MongoDB." };
    return { ok: false, error: `Remove failed (${r.status}).` };
  } catch {
    return { ok: false, error: "Backend unavailable." };
  }
}

export async function getDispatchPlan(): Promise<DispatchPlan> {
  const live = await tryLive<DispatchPlan>("/api/v3/dispatch/plan");
  return live ?? demo<DispatchPlan>("dispatch_plan.json");
}

// M4-reranked dispatch queue for a station (omit for city-wide). Tries the live
// backend (hourly-baked cache, else inline), then composes offline from the demo
// bundle so the reranked queue always renders. Honest: live_delay is SIMULATED.
export async function getDispatchQueue(
  station?: string | null,
  when: When = "now",
  hour?: number | null,
): Promise<DispatchQueue> {
  const qs = new URLSearchParams();
  if (station) qs.set("station", station);
  if (when) qs.set("when", when);
  if (hour != null) qs.set("hour", String(hour));
  const live = await tryLive<DispatchQueue>(`/api/v3/dispatch/queue?${qs}`);
  if (live && live.queue) return live;
  const [base, stations] = await Promise.all([demo<DemoCells>("cells.json"), getStations()]);
  return composeQueue(base.cells, stations, { station, when, hour: hour ?? undefined });
}

export async function getForecastDaily<T = unknown>(): Promise<T> {
  const live = await tryLive<T>("/api/v3/forecast/daily");
  return live ?? demo<T>("forecast_daily.json");
}

export async function getOnline<T = unknown>(): Promise<T> {
  const live = await tryLive<T>("/api/v3/online");
  return live ?? demo<T>("online.json");
}

export async function getEvaluation<T = unknown>(): Promise<T> {
  const live = await tryLive<T>("/api/v3/evaluation");
  return live ?? demo<T>("evaluation.json");
}

export async function getCausal<T = unknown>(): Promise<T> {
  const live = await tryLive<T>("/api/v3/causal");
  return live ?? demo<T>("causal.json");
}

export async function getSim<T = unknown>(): Promise<T> {
  const live = await tryLive<T>("/api/v3/sim");
  return live ?? demo<T>("sim_rl.json");
}

interface TicketFilter {
  role?: string;
  station?: string;
  status?: "open" | "closed";
  cell?: string;
  officer?: string | number; // assigned officer id or badge (per-officer view)
  limit?: number;
}

export async function getTickets(filter: TicketFilter = {}): Promise<Ticket[]> {
  const qs = new URLSearchParams();
  Object.entries(filter).forEach(([k, v]) => v != null && qs.set(k, String(v)));
  const live = await tryLive<Ticket[]>(`/api/v3/tickets?${qs}`);
  let rows = live;
  if (!rows) {
    local.seed((await demo<DemoCells>("cells.json")).cells, await demo<Ticket[]>("tickets.json"));
    rows = local.listTickets();
  }
  let out = rows;
  if (filter.station) out = out.filter((t) => (t.station || "").toLowerCase() === filter.station!.toLowerCase());
  if (filter.status) out = out.filter((t) => t.status === filter.status);
  if (filter.cell) out = out.filter((t) => t.cell === filter.cell);
  if (filter.officer != null) {
    const o = String(filter.officer).toUpperCase();
    out = out.filter((t) => String(t.assigned_officer ?? "") === o || (t.assigned_badge || "").toUpperCase() === o);
  }
  if (filter.limit) out = out.slice(0, filter.limit);
  return out;
}

// --------------------------------------------------------------------------- //
// Force / Taskforce (RBAC roster + officer CRUD + priority×area auto-allocation).
// Live -> /api/v3/force/* (auth-scoped to govt or the owning station). Offline ->
// a deterministic seeded roster (genRoster) so the demo always renders. Honesty:
// patrol/roster is operational planning, never a per-officer performance score.
// --------------------------------------------------------------------------- //
function rosterSummaryOf(officers: Officer[]): RosterSummary {
  const by_shift: Record<string, number> = {};
  SHIFT_ORDER.forEach((s) => (by_shift[s] = 0));
  const by_rank: Record<string, number> = {};
  RANKS.forEach((r) => (by_rank[r] = 0));
  for (const o of officers) {
    if (o.shift in by_shift) by_shift[o.shift] += 1;
    if (o.rank in by_rank) by_rank[o.rank] += 1;
  }
  return { total: officers.length, by_shift, by_rank };
}

export async function getForceMeta(): Promise<ForceMeta | null> {
  return (await tryLive<ForceMeta>("/api/v3/force/meta")) ?? null;
}

export async function getRoster(
  slug: string,
  opts: { nZones?: number; name?: string; lat?: number | null; lon?: number | null } = {},
): Promise<RosterPayload> {
  const nZones = opts.nZones ?? 12;
  try {
    const r = await fetch(`${BASE}/api/v3/force/roster?station=${encodeURIComponent(slug)}`, { headers: authHeader() });
    if (r.ok) return { ...(await r.json()), live: true };
  } catch {
    /* offline */
  }
  // offline: deterministic seed mirrors the backend so the demo always shows a roster
  const officers = genRoster(slug, nZones);
  return {
    station: { slug, name: opts.name ?? slug, lat: opts.lat ?? null, lon: opts.lon ?? null, n_zones: nZones, officers: officers.length, active: true },
    officers,
    ranks: RANKS,
    rank_abbr: RANK_ABBR,
    shifts: SHIFTS,
    shift_order: SHIFT_ORDER,
    summary: rosterSummaryOf(officers),
    live: false,
  };
}

export async function addOfficer(slug: string, name: string, rank: string, shift: string): Promise<Officer | null> {
  try {
    const r = await fetch(`${BASE}/api/v3/force/officers`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeader() },
      body: JSON.stringify({ station_slug: slug, name, rank, shift }),
    });
    if (r.ok) return (await r.json()) as Officer;
  } catch {
    /* offline -> caller keeps a local optimistic row */
  }
  return null;
}

export async function patchOfficer(oid: number, patch: { rank?: string; shift?: string; status?: string }): Promise<Officer | null> {
  try {
    const r = await fetch(`${BASE}/api/v3/force/officers/${oid}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", ...authHeader() },
      body: JSON.stringify(patch),
    });
    if (r.ok) return (await r.json()) as Officer;
  } catch {
    /* offline */
  }
  return null;
}

export async function removeOfficer(oid: number): Promise<boolean> {
  try {
    const r = await fetch(`${BASE}/api/v3/force/officers/${oid}`, { method: "DELETE", headers: authHeader() });
    return r.ok;
  } catch {
    return false;
  }
}

export async function autoAllocate(slug: string, shift?: string | null): Promise<AutoAllocation | null> {
  const qs = new URLSearchParams({ station: slug });
  if (shift) qs.set("shift", shift);
  try {
    const r = await fetch(`${BASE}/api/v3/force/auto-allocate?${qs}`, { method: "POST", headers: authHeader() });
    if (r.ok) return (await r.json()) as AutoAllocation;
  } catch {
    /* offline -> caller composes a local allocation from cells */
  }
  return null;
}

async function postLive<T>(path: string, body: unknown): Promise<T | null> {
  try {
    const r = await fetch(BASE + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(String(r.status));
    return (await r.json()) as T;
  } catch {
    setLive(false);
    return null;
  }
}

export async function postComplaint(input: ComplaintInput): Promise<Ticket> {
  const live = await postLive<Ticket>("/api/v3/complaints", input);
  if (live) return live;
  local.seed((await demo<DemoCells>("cells.json")).cells, await demo<Ticket[]>("tickets.json"));
  return local.postComplaint(input);
}

export async function postTicket(input: TicketInput): Promise<Ticket> {
  const live = await postLive<Ticket>("/api/v3/tickets", input);
  if (live) return live;
  local.seed((await demo<DemoCells>("cells.json")).cells, await demo<Ticket[]>("tickets.json"));
  return local.postTicket(input);
}

export async function patchTicket(id: string, body: ResolveInput): Promise<Ticket | null> {
  try {
    const r = await fetch(`${BASE}/api/v3/tickets/${encodeURIComponent(id)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (r.ok) return (await r.json()) as Ticket;
    throw new Error(String(r.status));
  } catch {
    setLive(false);
    return local.patchTicket(id, body);
  }
}
