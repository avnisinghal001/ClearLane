// Offline-first API client for the /api/v3 contract. Every read tries the live
// backend first (relative "/api" on Vercel, Vite proxy in dev, or an absolute
// VITE_API_BASE), and on ANY failure falls back to the bundled /demo-v3/*.json
// so the app always renders (judging safety). Writes try the backend, then fall
// back to the in-memory localStore mirror.
import { dowForWhen, dowLabel } from "./time";
import * as local from "./localStore";
import type {
  Cell,
  ComplaintInput,
  DispatchPlan,
  Kpis,
  MapPayload,
  ResolveInput,
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
function congAt(hc: DemoHourlyCongestion | null, roadClass: string | null | undefined, hour: number): number {
  if (!hc) return 1;
  const cur = hc.curves[roadClass || "unknown"] || hc.global || hc.curves["unknown"];
  const v = cur?.[((hour % 24) + 24) % 24];
  return v == null ? 0.5 : v;
}
const clamp100 = (x: number) => Math.max(0, Math.min(100, x));

// Compose the /api/v3/map payload offline from the cell base + KPIs, applying the
// time lens. The displayed `intensity` = historical PIC × modeled typical
// congestion for the active hour (the same honest model the backend serves).
function composeMap(when: When, hour: number | null, base: DemoCells, kpis: Kpis, hc: DemoHourlyCongestion | null): MapPayload {
  const isForecast = when !== "now";
  const dow = dowForWhen(when);
  const hr = hour ?? new Date().getHours();

  let maxBase = 1;
  const baseVal = new Map<string, number>();
  if (isForecast) {
    for (const c of base.cells) {
      const v = c.dow_curve ? c.dow_curve[dow] ?? 0 : (c.weekly_expected ?? 0) / 7 || c.intensity * 0.3;
      baseVal.set(c.h3_r10, v);
      if (v > maxBase) maxBase = v;
    }
  }

  const cells: Cell[] = base.cells.map((c) => {
    const adj = local.liveAdjustment(c.h3_r10);
    const op = clamp100(c.pic_score + adj);
    const cong = congAt(hc, c.road_class, hr);
    const mod = HC_BASE_W + HC_CONG_W * cong;
    let forecast_intensity: number | null = null;
    let intensity = c.intensity;
    if (isForecast) {
      const b = (baseVal.get(c.h3_r10) ?? 0) / maxBase;
      forecast_intensity = round(clamp100(b * 100 * mod), 1);
    } else {
      intensity = round(clamp100(c.pic_score * mod), 1); // hour-modulated live heat
    }
    return {
      ...c,
      intensity,
      forecast_intensity,
      congestion_hour: round(cong, 3),
      live_adjustment: round(adj, 1),
      operational_priority: round(op, 1),
    };
  });

  const hh = `${String(hr).padStart(2, "0")}:00`;
  const source_note = isForecast
    ? `Forecast · ${dowLabel(when)} @ ${hh} — modeled day-of-week propensity × modeled TYPICAL congestion for the hour. Congestion is modeled (commute pattern), not measured from tickets.`
    : `Live @ ${hh} — historical PIC × modeled TYPICAL congestion for the hour, + live boost. Congestion varies by hour; ticket counts are day-of-week (upload time).`;

  return {
    when,
    hour: hr,
    source: isForecast ? "forecast" : "live",
    source_note,
    cells,
    kpis,
    hour_profile: hc?.global ?? base.hour_profile,
    dow_order: base.dow_order,
  };
}

export async function getMap(when: When, hour: number | null): Promise<MapPayload> {
  const qs = new URLSearchParams({ when });
  if (hour != null) qs.set("hour", String(hour)); // hour drives the heatmap in every mode
  const live = await tryLive<MapPayload>(`/api/v3/map?${qs}`);
  if (live && live.cells) {
    return {
      ...live,
      when,
      hour: live.hour ?? hour,
      source: when === "now" ? "live" : "forecast",
      source_note: live.source_note ?? "",
    };
  }
  const [base, kpis, hc] = await Promise.all([
    demo<DemoCells>("cells.json"),
    demo<Kpis>("kpis.json"),
    demo<DemoHourlyCongestion>("hourly_congestion.json").catch(() => null),
  ]);
  local.seed(base.cells, await demo<Ticket[]>("tickets.json"));
  return composeMap(when, hour, base, kpis, hc);
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

export async function getDispatchPlan(): Promise<DispatchPlan> {
  const live = await tryLive<DispatchPlan>("/api/v3/dispatch/plan");
  return live ?? demo<DispatchPlan>("dispatch_plan.json");
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
  if (filter.limit) out = out.slice(0, filter.limit);
  return out;
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
