import { picColor } from "@/lib/format";
import { cellTier, flowColor, tierColor, type FlowImpactRanked } from "@/lib/signals";
import type { Cell, CongestionSource } from "@/lib/types";

// Traffic-signal density ramp for the heatmap: green (low) → yellow (medium) →
// red (highest). Matches the per-hour congestion story.
export const HEAT_GRADIENT: Record<number, string> = {
  0.15: "#16a34a",
  0.35: "#84cc16",
  0.5: "#facc15",
  0.7: "#f97316",
  0.85: "#ef4444",
  1.0: "#b91c1c",
};

// Honesty-aligned colours for the congestion-source layer.
export const SOURCE_HEX: Record<CongestionSource, string> = {
  live: "#16a34a",
  mappls_typical: "#f59e0b",
  modeled: "#4f7fd6",
  simulated: "#8b5cf6",
};

// v1 "Color zones by" set: priority tier · PIC · flow-impact proxy · operational
// boost · congestion source.
export type ColorMode = "tier" | "pic" | "flow" | "operational" | "source";

// Intensity used by the heatmap layer for the active time lens (learning-adjusted
// heat). Circle SIZING uses pressure/expected-activity directly (see ClearLaneMap).
export function displayIntensity(c: Cell, source: "live" | "forecast"): number {
  if (source === "forecast") return c.forecast_intensity ?? c.display_score ?? 0;
  return c.intensity ?? c.display_score ?? c.pic_score ?? 0;
}

// Time-varying composite (0..100) used by the "PIC / display score" colour mode so
// scrubbing the hour/day visibly RECOLOURS the map. Falls back to intensity/pic_score.
export function cellDisplayScore(c: Cell): number {
  return c.display_score ?? c.intensity ?? c.pic_score ?? 0;
}

export function circleColor(c: Cell, mode: ColorMode, flowMap?: Map<string, FlowImpactRanked>): string {
  if (mode === "source") return SOURCE_HEX[c.congestion_source] ?? SOURCE_HEX.modeled;
  if (mode === "operational") return picColor(c.operational_priority ?? c.pic_score);
  if (mode === "tier") return tierColor(cellTier(c));
  if (mode === "flow") return flowColor(flowMap?.get(c.h3_r10)?.score ?? 0);
  // "pic" = the TIME-VARYING display_score (green→yellow→red), recolours on scrub.
  return picColor(cellDisplayScore(c));
}

export function circleRadius(c: Cell, source: "live" | "forecast", maxIntensity: number): number {
  const v = displayIntensity(c, source);
  const t = maxIntensity > 0 ? v / maxIntensity : 0;
  return 4 + Math.sqrt(Math.max(0, t)) * 13;
}

export function heatPoints(cells: Cell[], source: "live" | "forecast"): [number, number, number][] {
  const max = Math.max(1, ...cells.map((c) => displayIntensity(c, source)));
  return cells
    .filter((c) => c.lat != null && c.lon != null)
    .map((c) => [c.lat, c.lon, Math.max(0.05, Math.min(1, displayIntensity(c, source) / max))]);
}
