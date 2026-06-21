import { picColor } from "@/lib/format";
import type { Cell, CongestionSource } from "@/lib/types";

// Legible density ramp for the heatmap (low → high). Tilted warm to match the
// civic-orange theme while staying readable.
export const HEAT_GRADIENT: Record<number, string> = {
  0.2: "#fde68a",
  0.4: "#fdba74",
  0.6: "#fb923c",
  0.78: "#f97316",
  0.9: "#ea580c",
  1.0: "#b91c1c",
};

// Honesty-aligned colours for the congestion-source layer.
export const SOURCE_HEX: Record<CongestionSource, string> = {
  live: "#16a34a",
  mappls_typical: "#f59e0b",
  modeled: "#4f7fd6",
};

export type ColorMode = "pic" | "source" | "operational";

// Intensity used by the heatmap + circle sizing for the active time lens.
export function displayIntensity(c: Cell, source: "live" | "forecast"): number {
  if (source === "forecast") return c.forecast_intensity ?? 0;
  return c.intensity ?? c.pic_score ?? 0;
}

export function circleColor(c: Cell, mode: ColorMode): string {
  if (mode === "source") return SOURCE_HEX[c.congestion_source] ?? SOURCE_HEX.modeled;
  if (mode === "operational") return picColor(c.operational_priority ?? c.pic_score);
  return picColor(c.pic_score);
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
