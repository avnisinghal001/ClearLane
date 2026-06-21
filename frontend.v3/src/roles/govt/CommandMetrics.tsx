import { useMemo } from "react";
import { Grid3x3, Flame, Repeat2, MoonStar, TrendingUp, ArrowUpRight, Radio } from "lucide-react";
import { cellTier, isBlindSpot, recurrenceScore } from "@/lib/signals";
import { dowForWhen } from "@/lib/time";
import type { Cell, Kpis } from "@/lib/types";

// Government command metrics strip — the at-a-glance city posture, all computed
// from the immutable ML cells + the live ops counts. Honest labels throughout.
export function CommandMetrics({ cells, kpis, liveOps }: { cells: Cell[]; kpis: Kpis | null; liveOps: number }) {
  const m = useMemo(() => {
    const today = dowForWhen("today");
    const tomorrow = dowForWhen("tomorrow");
    let p1 = 0;
    let chronic = 0;
    let blind = 0;
    let emerging = 0;
    let rising = 0;
    for (const c of cells) {
      const t = cellTier(c);
      if (t === "P1") p1++;
      if ((t === "P1" || t === "P2") && recurrenceScore(c) >= 70) chronic++;
      if (isBlindSpot(c)) blind++;
      if (c.emerging) emerging++;
      const curve = c.dow_curve;
      if (curve && curve.length === 7 && curve[tomorrow] > curve[today] * 1.02) rising++;
    }
    return { zones: cells.length, p1, chronic, blind, emerging: emerging || kpis?.online?.n_emerging || 0, rising };
  }, [cells, kpis]);

  const items = [
    { icon: Grid3x3, label: "Operational zones", value: m.zones, color: "text-foreground" },
    { icon: Flame, label: "P1 priority", value: m.p1, color: "text-destructive" },
    { icon: Repeat2, label: "Chronic", value: m.chronic, color: "text-amber-600" },
    { icon: MoonStar, label: "Evening blind spots", value: m.blind, color: "text-amber-600" },
    { icon: TrendingUp, label: "Emerging", value: m.emerging, color: "text-[hsl(var(--modeled))]" },
    { icon: ArrowUpRight, label: "Forecast-rising", value: m.rising, color: "text-[hsl(var(--modeled))]" },
    { icon: Radio, label: "Live ops", value: liveOps, color: "text-primary" },
  ];

  return (
    <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4 lg:grid-cols-7">
      {items.map((it) => {
        const Icon = it.icon;
        return (
          <div key={it.label} className="rounded-xl border bg-card p-3">
            <Icon className={`h-4 w-4 ${it.color}`} />
            <div className={`num mt-1.5 text-2xl font-bold leading-none ${it.color}`}>{it.value}</div>
            <div className="mt-1 text-[11px] font-medium leading-tight text-muted-foreground">{it.label}</div>
          </div>
        );
      })}
    </div>
  );
}
