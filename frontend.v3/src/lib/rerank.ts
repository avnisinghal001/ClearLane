// Offline mirror of the backend M4 dispatch reranker (api/clearlane/v3.py, which
// itself mirrors ml.v3/config.py RERANK_* — the SSOT). Used ONLY when the live
// /api/v3/dispatch/queue is unreachable, so the per-station reranked queue still
// renders against the bundled demo-v3 cells. The live backend is always preferred.
//
// HONESTY (carried over): `pressure` is MODELED from historical tickets, never a
// congestion measurement; `live_delay` here is the SIMULATED time/day congestion
// model (live Mappls ETA is not provisioned), labelled congestion_source. All
// aggregation is cell/station-level — never per officer.
import type { Cell, DispatchQueue, RerankComponent, RerankRow, Station, When } from "./types";

export const RERANK_WEIGHTS: Record<RerankComponent, number> = {
  forecast: 0.3,
  pressure: 0.25,
  under_observed: 0.15,
  live_delay: 0.2,
  reachability: 0.1,
};

const RERANK_REASON: Record<RerankComponent, string> = {
  forecast: "forecast pressure rising next month",
  pressure: "high modeled obstruction pressure",
  under_observed: "likely under-observed (blind-spot candidate)",
  reachability: "fast to reach from station",
  live_delay: "elevated congestion at this hour",
};

const UNDER_OBSERVED_REF = 200; // rank_divergence at/above this -> under_observed = 1
const DRIFT_REF = 3.0; // fallback: online drift z at/above this -> 1
const REACH_FLOOR_KM = 0.05;
const TIERS: [RerankRow["dispatch_tier"], number][] = [
  ["P1", 82],
  ["P2", 68],
  ["P3", 55],
];
const CELL_JITTER = 0.06;
const SIM_SEED = 1729;

// Calibrated so daytime baseline ≈ 0.70 and only the peaks approach 1.0 (mirror of
// the backend SIM_HOUR_FACTORS). Morning (~08–11) + evening (~17–21) peaks.
const SIM_HOUR_FACTORS = [
  0.34, 0.3, 0.28, 0.27, 0.3, 0.38, 0.52, 0.7, 0.92, 1.02, 0.96, 0.84, 0.74, 0.7, 0.7, 0.75, 0.84, 0.98, 1.08, 1.02,
  0.9, 0.78, 0.58, 0.42,
];
const SIM_DOW_FACTORS: Record<string, number> = {
  Mon: 0.9,
  Tue: 0.96,
  Wed: 1.0,
  Thu: 1.01,
  Fri: 1.06,
  Sat: 1.09,
  Sun: 1.14,
};

const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const clamp01 = (x: number) => Math.max(0, Math.min(1, x));
const clamp100 = (x: number) => Math.max(0, Math.min(100, x));

function slugify(name: string | null | undefined): string {
  return (name || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "station";
}

// Stable string hash (FNV-1a) -> deterministic per-cell jitter (no crypto, no async).
function cellJitter(cell: string): number {
  let h = 2166136261 ^ SIM_SEED;
  const s = `${SIM_SEED}:${cell}`;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  const frac = ((h >>> 0) % 1000) / 999;
  return (2 * frac - 1) * CELL_JITTER;
}

function simSeverity(baseSev: number | null | undefined, cell: string, hour: number, dow: string): number {
  const base = baseSev == null ? 0.5 : baseSev;
  const hf = SIM_HOUR_FACTORS[((hour % 24) + 24) % 24];
  const df = SIM_DOW_FACTORS[dow] ?? 1.0;
  return clamp01(base * hf * df * (1 + cellJitter(cell)));
}

function tier(score: number): RerankRow["dispatch_tier"] {
  for (const [t, thr] of TIERS) if (score >= thr) return t;
  return "P4";
}

function haversineKm(aLat: number, aLon: number, bLat: number, bLon: number): number {
  const R = 6371;
  const dLat = ((bLat - aLat) * Math.PI) / 180;
  const dLon = ((bLon - aLon) * Math.PI) / 180;
  const s =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((aLat * Math.PI) / 180) * Math.cos((bLat * Math.PI) / 180) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(s));
}

function reasonCodes(
  comp: Record<RerankComponent, number>,
  flags: { emerging: boolean; underCandidate: boolean; liveDelayNorm: number },
): string[] {
  const pairs = (Object.entries(comp) as [RerankComponent, number][])
    .filter(([k, v]) => k !== "live_delay" && v > 0)
    .sort((a, b) => b[1] - a[1]);
  const reasons = pairs.slice(0, 3).map(([k]) => RERANK_REASON[k]);
  const extra: string[] = [];
  if (flags.underCandidate && !reasons.includes(RERANK_REASON.under_observed)) extra.push(RERANK_REASON.under_observed);
  if (flags.emerging) extra.push("emerging — rising faster than the city");
  if (flags.liveDelayNorm >= 0.55) extra.push(`elevated simulated congestion now (+${Math.round(flags.liveDelayNorm * 100)}%)`);
  const out = [...reasons, ...extra.filter((f) => !reasons.includes(f))];
  return out.slice(0, 5).length ? out.slice(0, 5) : ["top modeled enforcement priority"];
}

export interface ComposeOpts {
  station?: string | null; // slug or name; omit -> city-wide
  when?: When;
  hour?: number;
  limit?: number;
}

// Build the reranked queue offline from the demo cells + station centroids.
export function composeQueue(cells: Cell[], stations: Station[], opts: ComposeOpts = {}): DispatchQueue {
  const when = opts.when ?? "now";
  const hour = opts.hour ?? new Date().getHours();
  const dow = DOW[(new Date().getDay() + 6) % 7]; // JS Sun=0 -> Mon=0 index
  const limit = opts.limit ?? 60;
  const slug = opts.station ? slugify(opts.station) : null;

  const ctr = new Map<string, Station>();
  for (const s of stations) ctr.set(s.slug, s);

  let fcMax = 1;
  for (const c of cells) if ((c.weekly_expected ?? 0) > fcMax) fcMax = c.weekly_expected ?? 1;

  const w = RERANK_WEIGHTS;
  const rows: RerankRow[] = [];
  for (const c of cells) {
    const stationName = c.police_station;
    const stSlug = slugify(stationName);
    if (slug && stSlug !== slug) continue;

    const forecastNorm = c.weekly_expected ? clamp01(c.weekly_expected / fcMax) : 0;
    const pressureNorm = clamp01((c.pic_score ?? 0) / 100);
    const rankDiv = c.rank_divergence ?? null;
    const underNorm =
      rankDiv != null ? clamp01(rankDiv / UNDER_OBSERVED_REF) : c.drift_z != null ? clamp01(c.drift_z / DRIFT_REF) : 0;
    const station = ctr.get(stSlug);
    const reachKm = station ? haversineKm(c.lat, c.lon, station.lat, station.lon) : null;
    const reachScore = reachKm != null ? 1 / (1 + Math.max(reachKm, REACH_FLOOR_KM)) : 0.5;
    const liveDelayNorm = simSeverity(c.congestion_severity, c.h3_r10, hour, dow);

    const comp: Record<RerankComponent, number> = {
      forecast: w.forecast * forecastNorm,
      pressure: w.pressure * pressureNorm,
      under_observed: w.under_observed * underNorm,
      live_delay: w.live_delay * liveDelayNorm,
      reachability: w.reachability * reachScore,
    };
    const raw = Object.values(comp).reduce((a, b) => a + b, 0);
    const score = Math.round(raw * 1000) / 10;
    const underCandidate = rankDiv != null ? rankDiv > 100 : (c.drift_z ?? 0) >= DRIFT_REF;

    rows.push({
      id: c.h3_r10,
      h3_r10: c.h3_r10,
      name: stationName ? `${stationName} · ${c.h3_r10.slice(0, 6)}` : `${c.h3_r10.slice(0, 9)}…`,
      station: stationName,
      station_slug: stSlug,
      lat: c.lat,
      lon: c.lon,
      road_class: c.road_class,
      rerank_score: score,
      rerank_raw: Math.round(raw * 1e4) / 1e4,
      dispatch_rank: 0,
      dispatch_tier: tier(score),
      components: Object.fromEntries(
        Object.entries(comp).map(([k, v]) => [k, Math.round(v * 1e4) / 1e4]),
      ) as Record<RerankComponent, number>,
      component_inputs: {
        forecast: Math.round(forecastNorm * 1e4) / 1e4,
        pressure: Math.round(pressureNorm * 1e4) / 1e4,
        under_observed: Math.round(underNorm * 1e4) / 1e4,
        live_delay: Math.round(liveDelayNorm * 1e4) / 1e4,
        reachability: Math.round(reachScore * 1e4) / 1e4,
      },
      pressure: Math.round((c.pic_score ?? 0) * 10) / 10,
      forecast_score: Math.round(forecastNorm * 1000) / 10,
      under_observed: Math.round(underNorm * 1000) / 10,
      under_observed_candidate: underCandidate,
      rank_divergence: rankDiv,
      emerging: !!c.emerging,
      drift_z: c.drift_z ?? null,
      sig_hot: false,
      on_route: false,
      assoc_score: Math.round(liveDelayNorm * 1000) / 10,
      congestion_source: "simulated",
      live_enriched: false,
      eta_min: reachKm != null ? Math.round((reachKm / 20) * 60 * 10) / 10 : null,
      reach_km: reachKm != null ? Math.round(reachKm * 100) / 100 : null,
      historical_priority: Math.round((c.pic_score ?? 0) * 10) / 10,
      live_adjustment: 0,
      operational_priority: clamp100(Math.round((c.pic_score ?? 0) * 10) / 10),
      reason_codes: reasonCodes(comp, { emerging: !!c.emerging, underCandidate, liveDelayNorm }),
    });
  }

  rows.sort((a, b) => b.rerank_raw - a.rerank_raw);
  const top = rows.slice(0, limit);
  top.forEach((r, i) => (r.dispatch_rank = i + 1));

  const station = slug ? ctr.get(slug) : null;
  return {
    station: slug,
    station_name: station?.station ?? (slug ? opts.station ?? null : null),
    scope: slug ? "station" : "city",
    when,
    hour,
    dow,
    congestion_source: "simulated",
    live_eta: false,
    fallback: "simulated",
    weights: w,
    reason_legend: RERANK_REASON,
    source: "offline-compose",
    from_cache: false,
    last_rerank: null,
    auto_interval_hours: 1,
    count: top.length,
    note: "Offline M4 rerank composed from the demo bundle (live API unavailable). pressure is MODELED, not measured; live_delay is the SIMULATED time/day congestion model.",
    queue: top,
  };
}
