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
  return () => liveListeners.delete(cb);
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
export async function getConfig(): Promise<{ mappls_key: string | null; demo?: boolean }> {
  const baked = import.meta.env.VITE_MAPPLS_KEY;
  if (baked) return { mappls_key: baked };
  try {
    return await getJSON<{ mappls_key: string | null }>(BASE + "/api/config");
  } catch {
    return demo<{ mappls_key: string | null; demo?: boolean }>("config.json");
  }
}

function round(x: number, d = 1) {
  const k = 10 ** d;
  return Math.round(x * k) / k;
}

// Compose the /api/v3/map payload offline from the cell base + KPIs, applying the
// time lens (now = live PIC; today/tomorrow@hour = modeled forecast layer).
function composeMap(when: When, hour: number | null, base: DemoCells, kpis: Kpis): MapPayload {
  const isForecast = when !== "now";
  const dow = dowForWhen(when);
  const hourW = isForecast && hour != null ? base.hour_profile?.[hour] ?? 1 : 1;

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
    const op = Math.max(0, Math.min(100, c.pic_score + adj));
    let forecast_intensity: number | null = null;
    if (isForecast) {
      const b = baseVal.get(c.h3_r10) ?? 0;
      forecast_intensity = round((b / maxBase) * 100 * hourW, 2);
    }
    return { ...c, forecast_intensity, live_adjustment: round(adj, 1), operational_priority: round(op, 1) };
  });

  const source_note = isForecast
    ? `Forecast — modeled expected violations for ${dowLabel(when)}${
        hour != null ? ` around ${hour}:00` : ""
      } (recorded weekday × modeled hour-of-day pattern). Not measured congestion.`
    : "Live snapshot — PIC = bias-corrected intensity × congestion severity. Severity provenance is badged per cell.";

  return {
    when,
    hour: isForecast ? hour : null,
    source: isForecast ? "forecast" : "live",
    source_note,
    cells,
    kpis,
    hour_profile: base.hour_profile,
    dow_order: base.dow_order,
  };
}

export async function getMap(when: When, hour: number | null): Promise<MapPayload> {
  const qs = new URLSearchParams({ when });
  if (hour != null && when !== "now") qs.set("hour", String(hour));
  const live = await tryLive<MapPayload>(`/api/v3/map?${qs}`);
  if (live && live.cells) {
    return {
      when,
      hour: when === "now" ? null : hour,
      source: when === "now" ? "live" : "forecast",
      source_note: live.source_note ?? "",
      ...live,
    };
  }
  const [base, kpis] = await Promise.all([demo<DemoCells>("cells.json"), demo<Kpis>("kpis.json")]);
  local.seed(base.cells, await demo<Ticket[]>("tickets.json"));
  return composeMap(when, hour, base, kpis);
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
