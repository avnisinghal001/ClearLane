import { useEffect, useMemo, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { MapPin, Radio, RefreshCw } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/DataTable";
import { SourceBadge } from "@/components/SourceBadge";
import { getDispatchQueue } from "@/lib/api";
import { picColor } from "@/lib/format";
import { relativeTime } from "@/lib/time";
import type { DispatchQueue as DispatchQueueT, RerankComponent, RerankRow } from "@/lib/types";

const TIER_VARIANT: Record<string, "destructive" | "warning" | "secondary"> = {
  P1: "destructive",
  P2: "warning",
  P3: "secondary",
  P4: "secondary",
};

const COMP_LABEL: Record<RerankComponent, string> = {
  forecast: "Forecast",
  pressure: "Pressure",
  under_observed: "Blind-spot",
  live_delay: "Congestion",
  reachability: "Reach",
};

// Compact horizontal breakdown of the five weighted M4 contributions (each 0..1).
function ComponentBar({ comp }: { comp: Record<RerankComponent, number> }) {
  const order: RerankComponent[] = ["forecast", "pressure", "under_observed", "live_delay", "reachability"];
  const colors: Record<RerankComponent, string> = {
    forecast: "hsl(var(--modeled))",
    pressure: "hsl(var(--warning))",
    under_observed: "hsl(var(--simulated))",
    live_delay: "hsl(var(--typical))",
    reachability: "hsl(var(--live))",
  };
  const total = order.reduce((a, k) => a + (comp[k] || 0), 0) || 1;
  return (
    <div className="w-36" title={order.map((k) => `${COMP_LABEL[k]}: ${(comp[k] * 100).toFixed(0)}`).join(" · ")}>
      <div className="flex h-2.5 overflow-hidden rounded-full bg-muted">
        {order.map((k) => (
          <div key={k} style={{ width: `${(comp[k] / total) * 100}%`, background: colors[k] }} />
        ))}
      </div>
    </div>
  );
}

export function DispatchQueue({ stationName, onFocus }: { stationName: string; onFocus: (lat: number, lon: number) => void }) {
  const [q, setQ] = useState<DispatchQueueT | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useMemo(
    () => () => {
      setLoading(true);
      getDispatchQueue(stationName, "now")
        .then(setQ)
        .finally(() => setLoading(false));
    },
    [stationName],
  );
  useEffect(() => load(), [load]);

  const columns = useMemo<ColumnDef<RerankRow>[]>(
    () => [
      {
        accessorKey: "dispatch_rank",
        header: "#",
        cell: ({ row }) => <span className="num font-bold text-muted-foreground">{row.original.dispatch_rank}</span>,
      },
      {
        accessorKey: "rerank_score",
        header: "Rerank",
        cell: ({ row }) => {
          const r = row.original;
          return (
            <div className="flex items-center gap-2">
              <span
                className="num inline-flex h-8 w-10 items-center justify-center rounded-md text-sm font-bold text-white"
                style={{ background: picColor(r.rerank_score) }}
              >
                {Math.round(r.rerank_score)}
              </span>
              <Badge variant={TIER_VARIANT[r.dispatch_tier]}>{r.dispatch_tier}</Badge>
            </div>
          );
        },
      },
      {
        id: "cell",
        header: "Cell",
        cell: ({ row }) => (
          <div className="min-w-0">
            <div className="font-mono text-xs text-muted-foreground">{row.original.h3_r10.slice(0, 10)}…</div>
            <div className="text-[11px] text-muted-foreground">
              PIC {Math.round(row.original.pressure)} · {row.original.road_class ?? "—"}
            </div>
          </div>
        ),
      },
      {
        id: "components",
        header: "Blend",
        cell: ({ row }) => <ComponentBar comp={row.original.components} />,
      },
      {
        id: "reasons",
        header: "Why this cell",
        cell: ({ row }) => (
          <div className="flex max-w-[20rem] flex-wrap gap-1">
            {row.original.reason_codes.slice(0, 3).map((rc, i) => (
              <Badge key={i} variant={i === 0 ? "default" : "secondary"} className="font-normal">
                {rc}
              </Badge>
            ))}
          </div>
        ),
      },
      {
        accessorKey: "operational_priority",
        header: "Op.",
        cell: ({ row }) => <span className="num font-semibold">{Math.round(row.original.operational_priority)}</span>,
      },
      {
        id: "focus",
        header: "",
        cell: ({ row }) => (
          <Button
            size="icon"
            variant="ghost"
            title="Show on map"
            onClick={(e) => {
              e.stopPropagation();
              onFocus(row.original.lat, row.original.lon);
            }}
          >
            <MapPin className="h-4 w-4" />
          </Button>
        ),
      },
    ],
    [onFocus],
  );

  const liveEta = q?.live_eta ?? false;

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2 text-base">
            <Radio className="h-4 w-4 text-primary" /> M4 dispatch queue
          </CardTitle>
          <div className="flex items-center gap-2">
            {/* live-vs-simulated indicator on the congestion/traffic signal */}
            <span className="text-[11px] text-muted-foreground">Congestion:</span>
            <SourceBadge source={q?.congestion_source ?? "simulated"} />
            <Badge variant={liveEta ? "live" : "secondary"} className="gap-1">
              <span className={`h-1.5 w-1.5 rounded-full ${liveEta ? "bg-[hsl(var(--live))]" : "bg-muted-foreground"}`} />
              {liveEta ? "Live ETA" : "Live ETA off"}
            </Badge>
            <Button size="sm" variant="outline" onClick={load} disabled={loading}>
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <DataTable
          columns={columns}
          data={q?.queue ?? []}
          initialSort={[{ id: "rerank_score", desc: true }]}
          pageSize={10}
          dense
          empty={loading ? "Loading reranked queue…" : "No reranked cells for this station."}
        />
        <p className="text-[11px] leading-tight text-muted-foreground">
          M4 rerank = forecast · pressure · under-observed · congestion · reachability (transparent linear blend).
          <span className="font-medium"> Pressure is MODELED from tickets — never a live congestion measurement.</span>{" "}
          {q?.fallback === "simulated"
            ? "Congestion stress is a SIMULATED time/day model (live Mappls ETA not provisioned)."
            : "Congestion stress from live Mappls ETA."}{" "}
          {q?.source === "rerank-cache"
            ? `Served from the hourly rerank cache${q?.last_rerank ? ` · updated ${relativeTime(new Date(q.last_rerank * 1000).toISOString())}` : ""}.`
            : q?.source === "offline-compose"
              ? "Composed offline from the demo bundle."
              : "Computed live."}{" "}
          Cell-level only — never per officer.
        </p>
      </CardContent>
    </Card>
  );
}
