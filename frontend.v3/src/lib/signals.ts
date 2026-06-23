// Derived v3 cell signals — the single source of truth that mirrors the v1 ML
// stages on the cell-centric data we already serve:
//   * priority tier (P1..P4) + the v1 green→amber→red ramp
//   * evening blind-spot / under-observed flag (ml/pipeline/06_timing_gap.py +
//     06b_blindspot.py — high-priority but under-observed, where the modeled
//     evening commute window bites)
//   * Carriageway Impact Index — a MODELED flow-impact proxy (ml/pipeline/
//     04_advanced.py _carriageway_impact): obstruction pressure scaled by static
//     road context (junction criticality, road class, metro/commercial proximity)
//   * intervention recommendation (04_advanced _intervention + the 06 evening sweep)
//
// HONESTY: every number here is MODELED from parking tickets / static road
// context — never a measurement of congestion (the data has no flow/speed signal).
// Aggregation is cell-level only; we never profile or rank individual officers.
import type { Cell } from "./types";

export type Tier = "P1" | "P2" | "P3" | "P4";

// v1 traffic-signal ramp (frontend/src/lib/format.js TIER_COLOR), green→red.
export const TIER_HEX: Record<Tier, string> = {
  P1: "#dc2626", // red-600   — highest
  P2: "#f97316", // orange-500
  P3: "#facc15", // yellow-400
  P4: "#16a34a", // green-600 — lowest
};
export const tierColor = (t: Tier) => TIER_HEX[t];

// Live-traffic congestion severity (0..1, Mappls TTI-derived) -> our P1..P4 ramp, so
// the live "busy streets" layer is coloured in the SAME theme as everything else
// (NORMAL green -> MODERATE yellow -> HIGH orange -> SEVERE red).
export function severityTier(sev: number | null | undefined): Tier {
  const s = sev ?? 0;
  if (s >= 0.55) return "P1";
  if (s >= 0.35) return "P2";
  if (s >= 0.15) return "P3";
  return "P4";
}
export const severityColor = (sev: number | null | undefined) => tierColor(severityTier(sev));

// PIC score (0..100) → priority tier. Fixed cuts so "Simple view" (P1/P2) and the
// command metrics read consistently across roles. Prefers the server-served `tier`
// (api/clearlane/v3._pic_tier uses the SAME cuts) and falls back to pic_score.
export function cellTier(c: Cell): Tier {
  if (c.tier === "P1" || c.tier === "P2" || c.tier === "P3" || c.tier === "P4") return c.tier;
  const s = c.pic_score ?? 0;
  if (s >= 66) return "P1";
  if (s >= 44) return "P2";
  if (s >= 24) return "P3";
  return "P4";
}

// Under-observed signal (ml/pipeline/06b_blindspot.py): NB rank_divergence
// (rank_naive − rank_bias) high, else online drift, else emerging. The honest v3
// "blind spot" = a high-priority cell that enforcement under-covers — exactly the
// kind the modeled evening commute window (17:00–21:00) is most likely to miss.
export function underObserved(c: Cell): boolean {
  return (c.rank_divergence ?? 0) >= 90 || (c.drift_z ?? 0) >= 1.5 || !!c.emerging;
}

export function isBlindSpot(c: Cell): boolean {
  const t = cellTier(c);
  return (t === "P1" || t === "P2") && underObserved(c);
}

// --------------------------------------------------------------------------- //
// Carriageway Impact Index — MODELED flow-impact proxy (mirror of 04_advanced).
// --------------------------------------------------------------------------- //
// Static road-class weights (v1 ml/pipeline config ROAD_CLASS_WEIGHTS).
const ROAD_CLASS_WEIGHTS: Record<string, number> = {
  ring_road: 1.0,
  arterial: 0.9,
  commercial: 0.75,
  main_road: 0.6,
  local: 0.35,
  unknown: 0.5,
};
// Junction criticality is not in the cell artifact, so we proxy it from the road
// class (arterials/ring-roads are junction-dense) — a transparent, bounded stand-in.
const JUNCTION_BY_CLASS: Record<string, number> = {
  ring_road: 0.9,
  arterial: 0.8,
  commercial: 0.6,
  main_road: 0.5,
  local: 0.2,
  unknown: 0.4,
};
const CII_WEIGHTS = { junction: 0.45, road_class: 0.35, demand: 0.2 };
const CII_CLIP: [number, number] = [0.85, 1.6]; // bounded context multiplier
const POI_FAR_M = 1200; // beyond this a demand generator stops boosting impact

export const ROAD_CLASS_LABEL: Record<string, string> = {
  ring_road: "Ring road",
  arterial: "Arterial / junction",
  main_road: "Main road",
  commercial: "Commercial core",
  local: "Local street",
  unknown: "Unclassified",
};

// Public landmark coordinates (Namma Metro stations + commercial hubs). Audited
// static reference, mirroring v1 ml/pipeline/anchors.py — used only for proximity.
export const METRO: [number, number][] = [
  [12.9756, 77.5727], [12.9756, 77.6068], [12.9784, 77.6408], [12.9766, 77.5907],
  [12.9796, 77.5905], [12.9728, 77.6201], [12.9907, 77.6536], [13.0234, 77.55],
  [12.9912, 77.555], [13.0061, 77.5709], [12.9301, 77.5803], [12.9255, 77.5734],
  [12.8602, 77.5283], [13.048, 77.5], [12.9921, 77.7585],
];
export const COMMERCIAL: [number, number][] = [
  [12.9744, 77.6094], [12.9829, 77.6092], [12.969, 77.576], [12.961, 77.577],
  [12.925, 77.5938], [12.9352, 77.6245], [12.9719, 77.6412], [12.8452, 77.6602],
  [12.9856, 77.7367], [13.003, 77.5712],
];

function haversineM(aLat: number, aLon: number, bLat: number, bLon: number): number {
  const R = 6_371_000;
  const dLat = ((bLat - aLat) * Math.PI) / 180;
  const dLon = ((bLon - aLon) * Math.PI) / 180;
  const s =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((aLat * Math.PI) / 180) * Math.cos((bLat * Math.PI) / 180) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(s));
}
function nearestAnchorM(lat: number, lon: number, anchors: [number, number][]): number {
  let best = Infinity;
  for (const [aLat, aLon] of anchors) best = Math.min(best, haversineM(lat, lon, aLat, aLon));
  return best;
}
const demandProximity = (distM: number) => Math.max(0, Math.min(1, 1 - distM / POI_FAR_M));
const clamp = (x: number, lo = 0, hi = 100) => Math.max(lo, Math.min(hi, x));

export interface FlowImpact {
  raw: number; // pressure × context multiplier (unnormalized)
  multiplier: number; // 0.85..1.6 bounded context multiplier
  junction: number; // 0..1 junction criticality (proxy)
  road_class: string;
  road_weight: number;
  dist_metro_m: number;
  dist_commercial_m: number;
  demand: number; // 0..1
}

// Per-cell flow-impact components (no rank/normalized score — that needs the city).
export function flowImpact(c: Cell): FlowImpact {
  const rc = c.road_class || "unknown";
  const roadWeight = ROAD_CLASS_WEIGHTS[rc] ?? ROAD_CLASS_WEIGHTS.unknown;
  const junction = JUNCTION_BY_CLASS[rc] ?? JUNCTION_BY_CLASS.unknown;
  const dm = nearestAnchorM(c.lat, c.lon, METRO);
  const dc = nearestAnchorM(c.lat, c.lon, COMMERCIAL);
  const demand = Math.max(demandProximity(dm), demandProximity(dc));
  const m = CII_WEIGHTS.junction * junction + CII_WEIGHTS.road_class * roadWeight + CII_WEIGHTS.demand * demand;
  const [lo, hi] = CII_CLIP;
  const multiplier = Math.max(lo, Math.min(hi, lo + m * (hi - lo)));
  return {
    raw: (c.pic_score ?? 0) * multiplier,
    multiplier: Math.round(multiplier * 100) / 100,
    junction,
    road_class: rc,
    road_weight: Math.round(roadWeight * 100) / 100,
    dist_metro_m: Math.round(dm),
    dist_commercial_m: Math.round(dc),
    demand,
  };
}

export interface FlowImpactRanked extends FlowImpact {
  score: number; // 0..100 normalized vs the busiest cell
  rank: number; // 1 = highest flow impact among the supplied cells
}

// Flow-impact for every cell, normalized + ranked (mirrors percentile_norm + rank).
export function flowImpactTable(cells: Cell[]): Map<string, FlowImpactRanked> {
  const recs = cells.map((c) => ({ h3: c.h3_r10, fi: flowImpact(c) }));
  const max = Math.max(1, ...recs.map((r) => r.fi.raw));
  const ordered = [...recs].sort((a, b) => b.fi.raw - a.fi.raw);
  const rankByH3 = new Map<string, number>();
  ordered.forEach((r, i) => rankByH3.set(r.h3, i + 1));
  const out = new Map<string, FlowImpactRanked>();
  for (const r of recs) {
    out.set(r.h3, { ...r.fi, score: Math.round((r.fi.raw / max) * 1000) / 10, rank: rankByH3.get(r.h3) ?? 0 });
  }
  return out;
}

// flow-impact gradient: accent-blue (low) → red (high) — the v1 LiveMap flowColor.
export function flowColor(score: number): string {
  const t = Math.max(0, Math.min(1, (score ?? 0) / 100));
  const a = [55, 138, 221];
  const b = [220, 38, 38];
  const c = a.map((x, i) => Math.round(x + (b[i] - x) * t));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

// --------------------------------------------------------------------------- //
// Per-cell dials (Pressure / Recurrence / Emergence / Priority) + intervention.
// --------------------------------------------------------------------------- //
export function pressureScore(c: Cell): number {
  return Math.round(c.pic_score ?? 0);
}

// Recurrence (chronic-ness): how evenly the weekday demand is spread. A cell hot
// every weekday → high recurrence; a one-day spike → low. Derived from dow_curve.
export function recurrenceScore(c: Cell): number {
  const curve = c.dow_curve;
  if (!curve || !curve.length) return 0;
  const mean = curve.reduce((a, b) => a + b, 0) / curve.length;
  const max = Math.max(...curve);
  if (max <= 0) return 0;
  return Math.round((mean / max) * 100);
}

// Emergence: online drift (stage 09). Emerging cells score high; cooling ones low.
export function emergenceScore(c: Cell): number {
  const z = c.drift_z ?? 0;
  if (c.emerging) return Math.round(clamp(60 + z * 12));
  return Math.round(clamp(z * 20));
}

export function priorityScore(c: Cell): number {
  return Math.round(c.operational_priority ?? c.pic_score ?? 0);
}

export interface Intervention {
  action: string;
  window: string;
}

export function intervention(c: Cell): Intervention {
  const t = cellTier(c);
  const blind = isBlindSpot(c);
  const window = blind
    ? "Add an evening sweep 17:00–21:00 (modeled commute peak)"
    : "Daytime enforcement window";
  if (t === "P1" || t === "P2") {
    if (c.road_class === "ring_road" || c.road_class === "arterial")
      return { action: "Fixed no-parking board + junction sweep (arterial choke point)", window };
    if (c.emerging) return { action: "Rapid patrol — emerging hotspot rising faster than the city", window };
    if (c.road_class === "commercial")
      return { action: "Continuous corridor patrol / barricading (commercial demand)", window };
    return { action: "Targeted enforcement sweep", window };
  }
  return { action: "Monitor", window: "—" };
}

// --------------------------------------------------------------------------- //
// Plain-language presentation helpers (product polish). These translate the same
// MODELED signals above into human copy for the citizen/police detail card —
// they NEVER introduce a new claim. Aggregation stays cell-level only.
// --------------------------------------------------------------------------- //
export type ChipTone = "destructive" | "warning" | "modeled" | "secondary" | "success";
export interface WhyChip {
  label: string;
  tone: ChipTone;
}

const TIER_WORD: Record<Tier, string> = { P1: "High", P2: "Elevated", P3: "Moderate", P4: "Low" };
const TIER_BLURB: Record<Tier, string> = {
  P1: "One of the worst parking spots in this area — needs regular enforcement.",
  P2: "A recurring problem spot worth patrolling.",
  P3: "Some parking trouble here, but not a top priority.",
  P4: "Mostly clear — only occasional parking issues.",
};

export interface PriorityLabel {
  tier: Tier;
  word: string; // High / Elevated / Moderate / Low
  blurb: string;
  color: string;
}

export function priorityLabel(c: Cell): PriorityLabel {
  const tier = cellTier(c);
  return { tier, word: TIER_WORD[tier], blurb: TIER_BLURB[tier], color: tierColor(tier) };
}

// Human "why it's flagged" chips, derived only from signals we actually have.
// Order = most useful first; capped so the card stays scannable.
export function whyFlagged(c: Cell): WhyChip[] {
  const chips: WhyChip[] = [];
  const tier = cellTier(c);
  const hot = tier === "P1" || tier === "P2";

  if (c.emerging) chips.push({ label: "Rising activity", tone: "warning" });
  else if ((c.drift_z ?? 0) >= 1) chips.push({ label: "Picking up lately", tone: "warning" });

  if (isBlindSpot(c)) chips.push({ label: "Evening blind spot", tone: "modeled" });

  if (hot && recurrenceScore(c) >= 60) chips.push({ label: "Chronic hotspot", tone: "destructive" });

  if (c.road_class === "ring_road" || c.road_class === "arterial")
    chips.push({ label: "Major-road choke point", tone: "secondary" });
  else if (c.road_class === "commercial") chips.push({ label: "Busy market area", tone: "secondary" });

  if (c.peak_dow) chips.push({ label: `Worst on ${c.peak_dow}`, tone: "secondary" });

  if (!chips.length)
    chips.push(hot ? { label: "Frequent violations", tone: "destructive" } : { label: "Occasional violations", tone: "secondary" });

  return chips.slice(0, 4);
}
