import { Layers, TrendingUp, Crosshair, Activity, BadgeCheck } from "lucide-react";
import { Kpi } from "@/components/Kpi";
import { num, pct } from "@/lib/format";
import type { Kpis } from "@/lib/types";

export function KpiStrip({ k }: { k: Kpis }) {
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-6">
      <Kpi
        label="Top-2.5% concentration"
        value={pct(k.concentration.top_2_5_pct_share)}
        sub={`of all violations from ${num(k.concentration.top_2_5_pct_cells)} hottest cells`}
        icon={<Layers className="h-5 w-5" />}
        tone="primary"
      />
      <Kpi
        label="PIC coverage"
        value={pct(k.dispatch.covered_pct)}
        sub={`${k.dispatch.officers} officers · exact MCLP`}
        icon={<Crosshair className="h-5 w-5" />}
        tone="success"
      />
      <Kpi
        label="Dispatch uplift"
        value={`${k.dispatch.uplift_vs_random.toFixed(2)}×`}
        sub="vs random deployment"
        icon={<TrendingUp className="h-5 w-5" />}
      />
      <Kpi
        label="Forecaster"
        value={`ρ ${k.forecaster.spearman.toFixed(2)}`}
        sub={k.forecaster.beats_baseline ? `beats baseline (dev ${k.forecaster.poisson_deviance.toFixed(2)} < ${k.forecaster.baseline_poisson_deviance.toFixed(2)})` : "—"}
        icon={<Activity className="h-5 w-5" />}
        tone={k.forecaster.beats_baseline ? "success" : "default"}
      />
      <Kpi
        label="Emerging hotspots"
        value={num(k.online.n_emerging)}
        sub={`${pct(k.online.emerging_share * 100, 1)} of eligible cells`}
        icon={<TrendingUp className="h-5 w-5" />}
        tone="warning"
      />
      <Kpi
        label="Validations passed"
        value={`${k.capabilities.n_pass}/${k.capabilities.n_total}`}
        sub="auditable capability bars"
        icon={<BadgeCheck className="h-5 w-5" />}
        tone="success"
      />
    </div>
  );
}
