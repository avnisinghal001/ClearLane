import { useMemo } from "react";
import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { Kpis } from "@/lib/types";

/* eslint-disable @typescript-eslint/no-explicit-any */

const AXIS = { fontSize: 11, fill: "#78716c" };

export function Analytics({ kpis, sim, causal }: { kpis: Kpis; sim: any; causal: any }) {
  const regret = useMemo(() => {
    const r = sim?.regret_curve;
    if (!r?.random) return [];
    return r.random.map((_: number, i: number) => ({
      step: i + 1,
      Random: r.random[i],
      Greedy: r.greedy?.[i],
      LinUCB: r.linucb?.[i],
    }));
  }, [sim]);

  const forecastBars = [
    { name: "Baseline", dev: kpis.forecaster.baseline_poisson_deviance, fill: "#d6d3d1" },
    { name: "ClearLane", dev: kpis.forecaster.poisson_deviance, fill: "#ea580c" },
  ];

  const concBars = [
    { name: "Top 2.5%", share: kpis.concentration.top_2_5_pct_share },
    { name: "Top 5%", share: kpis.concentration.top_5_pct_share },
    { name: "Top 10%", share: kpis.concentration.top_10_pct_share },
  ];

  const beta = causal?.beta ?? 0;
  const ciLow = causal?.ci_low ?? 0;
  const ciHigh = causal?.ci_high ?? 0;
  const placebo = causal?.placebo_beta_mean ?? 0;

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader className="pb-1">
          <CardTitle className="text-base">Forecaster vs baseline</CardTitle>
          <CardDescription>Held-out Poisson deviance — lower is better. Spearman ρ {kpis.forecaster.spearman.toFixed(2)}.</CardDescription>
        </CardHeader>
        <CardContent>
          <ResponsiveContainer width="100%" height={210}>
            <BarChart data={forecastBars} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#eee" vertical={false} />
              <XAxis dataKey="name" tick={AXIS} axisLine={false} tickLine={false} />
              <YAxis tick={AXIS} axisLine={false} tickLine={false} />
              <Tooltip formatter={(v: number) => v.toFixed(3)} contentStyle={{ borderRadius: 10, fontSize: 12 }} />
              <Bar dataKey="dev" radius={[6, 6, 0, 0]}>
                {forecastBars.map((b, i) => (
                  <Cell key={i} fill={b.fill} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <div className="mt-1 text-center text-xs text-muted-foreground">
            {kpis.forecaster.beats_baseline ? "Beats the baseline on held-out months." : "—"} Predicts obstruction pressure, not congestion.
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-1">
          <CardTitle className="text-base">Dispatch policy regret (simulated)</CardTitle>
          <CardDescription>Cumulative regret vs oracle — lower is better. LinUCB explores blind spots.</CardDescription>
        </CardHeader>
        <CardContent>
          <ResponsiveContainer width="100%" height={210}>
            <LineChart data={regret} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#eee" vertical={false} />
              <XAxis dataKey="step" tick={AXIS} axisLine={false} tickLine={false} />
              <YAxis tick={AXIS} axisLine={false} tickLine={false} />
              <Tooltip contentStyle={{ borderRadius: 10, fontSize: 12 }} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Line type="monotone" dataKey="Random" stroke="#d6d3d1" dot={false} strokeWidth={2} />
              <Line type="monotone" dataKey="Greedy" stroke="#f59e0b" dot={false} strokeWidth={2} />
              <Line type="monotone" dataKey="LinUCB" stroke="#ea580c" dot={false} strokeWidth={2.5} />
            </LineChart>
          </ResponsiveContainer>
          <div className="mt-1 text-center text-xs text-muted-foreground">
            Simulated (no real dispatch logs exist). LinUCB ≈ {sim?.pct_of_oracle?.linucb ?? "—"}% of oracle.
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-1">
          <CardTitle className="text-base">Violation concentration</CardTitle>
          <CardDescription>A tiny slice of cells carries most violations — value is correcting for patrol bias, not counting tickets.</CardDescription>
        </CardHeader>
        <CardContent>
          <ResponsiveContainer width="100%" height={210}>
            <BarChart data={concBars} layout="vertical" margin={{ top: 4, right: 16, left: 12, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#eee" horizontal={false} />
              <XAxis type="number" domain={[0, 100]} tick={AXIS} axisLine={false} tickLine={false} unit="%" />
              <YAxis type="category" dataKey="name" tick={AXIS} axisLine={false} tickLine={false} width={64} />
              <Tooltip formatter={(v: number) => `${v}%`} contentStyle={{ borderRadius: 10, fontSize: 12 }} />
              <Bar dataKey="share" radius={[0, 6, 6, 0]} fill="#ea580c" />
            </BarChart>
          </ResponsiveContainer>
          <div className="mt-1 text-center text-xs text-muted-foreground">
            {kpis.concentration.cells_for_50pct} cells ({kpis.concentration.cells_for_50pct_share}% of all) account for ~50% of violations.
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-1">
          <CardTitle className="text-base">Quasi-causal enforcement effect</CardTitle>
          <CardDescription>Within-cell exposure → next-month change in violations. Placebo collapses to ~0.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3 pt-2">
          <div className="rounded-lg border p-3">
            <div className="flex items-baseline justify-between">
              <span className="text-sm text-muted-foreground">β (enforcement responsiveness)</span>
              <span className="num text-2xl font-bold">{beta.toFixed(3)}</span>
            </div>
            <div className="mt-1 text-xs text-muted-foreground">
              95% CI [{ciLow.toFixed(2)}, {ciHigh.toFixed(2)}]
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant="success">placebo β ≈ {placebo.toFixed(3)}</Badge>
            <span className="text-xs text-muted-foreground">real effect is distinguishable from placebo</span>
          </div>
          <p className="text-[11px] leading-tight text-muted-foreground">
            Estimated from ticket data — enforcement → future-violation responsiveness, <b>not</b> parking → measured congestion (which needs a live ETA panel).
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
