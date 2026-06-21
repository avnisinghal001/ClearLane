import { useState } from "react";
import {
  RefreshCw, Loader2, Grid3x3, Crosshair, Gauge, Clock,
  CalendarClock, Route as RouteIcon, Brain, CheckCircle2, ArrowRight,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { toast } from "@/components/toast";
import { forceRecompute } from "@/lib/api";
import type { Kpis } from "@/lib/types";

// The ordered story of how the day's deployment plan is built — each step says
// what it does, what it helps with, and how it feeds the NEXT plan of action.
const STEPS = [
  {
    icon: Grid3x3, tag: "01 · Ingest",
    title: "Clean & H3 bin + exposure",
    does: "Every ticket → a 65 m hex cell, with enforcement exposure (distinct officers × active days).",
    helps: "Strips patrol bias so a hotspot isn't just 'where police already look'.",
  },
  {
    icon: Crosshair, tag: "02 · Detect",
    title: "Bias-corrected hotspots",
    does: "Negative-Binomial rate model + Getis-Ord Gi* significance on the exposure-corrected rate.",
    helps: "Surfaces the TRUE illegal-parking hotspots — including under-policed cells a count map misses.",
  },
  {
    icon: Gauge, tag: "03 · Score",
    title: "PIC — parking-induced congestion",
    does: "Intensity × congestion severity → one 0–100 score per cell.",
    helps: "Ranks where illegal parking actually chokes a carriageway, not just where it's frequent.",
  },
  {
    icon: Clock, tag: "04 · Time",
    title: "Hourly congestion overlay",
    does: "Historical PIC × a modeled 24-hour typical-congestion curve (per road class).",
    helps: "Tells you WHEN each hotspot bites today — the morning vs evening deployment windows.",
  },
  {
    icon: CalendarClock, tag: "05 · Forecast",
    title: "Day-ahead propensity",
    does: "LightGBM day-of-week forecaster (temporal holdout) per cell.",
    helps: "Builds tomorrow's plan: which cells stay/become hot next.",
  },
  {
    icon: RouteIcon, tag: "06 · Deploy",
    title: "Dispatch plan (MCLP + VRP)",
    does: "Optimises officer placement to cover the most PIC, then routes each station's stops.",
    helps: "Turns the map into a concrete who-goes-where patrol plan.",
  },
  {
    icon: Brain, tag: "07 · Learn",
    title: "Online self-learning",
    does: "Folds citizen complaints + officer outcomes into each cell's Gamma-Poisson rate (hourly).",
    helps: "Catches emerging hotspots and re-ranks the next dispatch — the loop that improves daily.",
  },
];

export function GovtPlaybook({ kpis, onDone }: { kpis: Kpis | null; onDone?: () => void }) {
  const [busy, setBusy] = useState(false);
  const [last, setLast] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    const res = await forceRecompute();
    setBusy(false);
    if (res.ok) {
      const n = res.heatmap?.n_cells ?? 0;
      const upd = (res.recompute?.n_cells_updated as number) ?? 0;
      setLast(new Date().toLocaleTimeString());
      toast(`Recomputed · ${upd} cells updated · ${n} hourly heatmaps re-baked`, { tone: "success" });
      onDone?.();
    } else {
      toast(res.error ?? "Recompute failed.", { tone: "warning" });
    }
  }

  return (
    <Card className="overflow-hidden">
      <CardContent className="p-4 sm:p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-base font-bold">How today's plan is built</h3>
              <Badge variant="modeled">7-stage ML pipeline</Badge>
            </div>
            <p className="mt-0.5 text-sm text-muted-foreground">
              Each stage feeds the next — ending in a ranked, hour-aware deployment plan. Force a recompute to
              fold in the latest citizen + officer feedback and re-bake the hourly heatmaps.
            </p>
          </div>
          <div className="flex flex-col items-end gap-1">
            <Button onClick={run} disabled={busy} className="gap-2">
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              {busy ? "Recomputing…" : "Force update now"}
            </Button>
            {last && <span className="text-[11px] text-muted-foreground">last forced · {last}</span>}
          </div>
        </div>

        {/* ordered, reranked pipeline cards */}
        <div className="mt-4 grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
          {STEPS.map((s, i) => {
            const Icon = s.icon;
            return (
              <div key={s.tag} className="relative rounded-xl border bg-card p-3 transition-shadow hover:shadow-sm">
                <div className="flex items-center gap-2">
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                    <Icon className="h-4 w-4" />
                  </span>
                  <div className="min-w-0">
                    <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{s.tag}</div>
                    <div className="truncate text-sm font-semibold">{s.title}</div>
                  </div>
                </div>
                <p className="mt-2 text-xs text-muted-foreground">{s.does}</p>
                <p className="mt-1.5 flex items-start gap-1 text-xs font-medium text-foreground">
                  <ArrowRight className="mt-0.5 h-3 w-3 shrink-0 text-primary" />
                  {s.helps}
                </p>
                {i === STEPS.length - 1 && (
                  <div className="mt-2 flex items-center gap-1 text-[11px] text-emerald-600">
                    <CheckCircle2 className="h-3 w-3" /> Loops back to step 02 → next plan of action
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {kpis && (
          <p className="mt-3 text-[11px] text-muted-foreground">
            Current loop: {kpis.online?.n_emerging ?? 0} emerging hotspots · forecaster Spearman{" "}
            {kpis.forecaster?.spearman ?? "—"} · dispatch covers {kpis.dispatch?.covered_pct ?? "—"}% of PIC.
            Historical ML scores are never edited by the live loop — only re-ranked.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
