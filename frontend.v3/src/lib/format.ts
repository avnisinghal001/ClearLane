import type { CongestionSource } from "./types";

export const num = (x: number | null | undefined, d = 0): string =>
  x == null || Number.isNaN(x) ? "—" : (+x).toLocaleString("en-IN", { maximumFractionDigits: d });

export const pct = (x: number | null | undefined, d = 0): string =>
  x == null || Number.isNaN(x) ? "—" : `${(+x).toFixed(d)}%`;

export const compact = (x: number | null | undefined): string =>
  x == null || Number.isNaN(x) ? "—" : Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 }).format(x);

// Honesty: badge the provenance of the congestion-severity number.
export const SOURCE_META: Record<CongestionSource, { label: string; variant: "live" | "typical" | "modeled"; help: string }> = {
  live: {
    label: "Live",
    variant: "live",
    help: "Severity from live Mappls travel-time ratio (real-time).",
  },
  mappls_typical: {
    label: "Typical",
    variant: "typical",
    help: "Mappls historical TYPICAL-traffic ratio — not real-time, not a measurement from tickets.",
  },
  modeled: {
    label: "Modeled",
    variant: "modeled",
    help: "Modeled severity proxy (live Mappls ETA upgrades it in place when enabled). Not measured congestion.",
  },
};

export const sourceMeta = (s: CongestionSource | undefined | null) => SOURCE_META[s ?? "modeled"] ?? SOURCE_META.modeled;

// Orange → red ramp for PIC / priority scores (0..100). Matches the civic theme.
export function picColor(score: number): string {
  const t = Math.max(0, Math.min(1, (score ?? 0) / 100));
  // light amber (low) -> deep red (high)
  const stops: [number, [number, number, number]][] = [
    [0.0, [253, 230, 138]], // amber-200
    [0.45, [251, 146, 60]], // orange-400
    [0.72, [234, 88, 12]], // orange-600
    [1.0, [185, 28, 28]], // red-700
  ];
  let a = stops[0], b = stops[stops.length - 1];
  for (let i = 0; i < stops.length - 1; i++) {
    if (t >= stops[i][0] && t <= stops[i + 1][0]) {
      a = stops[i];
      b = stops[i + 1];
      break;
    }
  }
  const span = b[0] - a[0] || 1;
  const k = (t - a[0]) / span;
  const c = a[1].map((v, i) => Math.round(v + (b[1][i] - v) * k));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

export function severityLabel(sev: number): string {
  if (sev >= 0.85) return "Severe";
  if (sev >= 0.65) return "High";
  if (sev >= 0.4) return "Moderate";
  return "Low";
}

export const titleCase = (s: string | null | undefined): string =>
  (s ?? "").toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());

export const mapsUrl = (lat: number, lon: number) => `https://www.google.com/maps?q=${lat},${lon}`;
