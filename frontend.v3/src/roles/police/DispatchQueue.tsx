import { useEffect, useMemo, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { MapPin, Radio, RefreshCw } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/DataTable";
import { getDispatchQueue } from "@/lib/api";
import { picColor } from "@/lib/format";
import { relativeTime } from "@/lib/time";
import type { DispatchQueue as DispatchQueueT, RerankComponent, RerankRow, When } from "@/lib/types";

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

export function DispatchQueue({
  stationName,
  when = "now",
  hour,
  onFocus,
}: {
  stationName: string;
  when?: When;
  hour?: number;
  onFocus: (lat: number, lon: number, h3?: string) => void;
}) {
  const [q, setQ] = useState<DispatchQueueT | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useMemo(
    () => () => {
      setLoading(true);
      getDispatchQueue(stationName || null, when, hour)
        .then(setQ)
        .finally(() => setLoading(false));
    },
    [stationName, when, hour],
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
        header: "Priority",
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
        header: "Area",
        cell: ({ row }) => (
          <div className="min-w-0">
            <div className="truncate text-xs font-medium">{row.original.road_class?.replace(/_/g, " ") ?? row.original.station ?? "Priority area"}</div>
            <div className="text-[11px] text-muted-foreground">
              {row.original.station ?? "City-wide"} · Pressure {Math.round(row.original.pressure)}
            </div>
          </div>
        ),
      },
      {
        id: "components",
        header: "Factors",
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
        header: "Now",
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
              onFocus(row.original.lat, row.original.lon, row.original.h3_r10);
            }}
          >
            <MapPin className="h-4 w-4" />
          </Button>
        ),
      },
    ],
    [onFocus],
  );

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2 text-base">
            <Radio className="h-4 w-4 text-primary" /> Where to deploy now
          </CardTitle>
          <Button size="sm" variant="outline" onClick={load} disabled={loading}>
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          </Button>
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
          Lens: {q?.when ?? when} · {q?.dow ?? "—"} · {String(q?.hour ?? hour ?? "—").padStart(2, "0")}:00.{" "}
          Ranked by what needs attention now — recent trend, how chronic the spot is, evening blind-spots, congestion, and how fast a patrol can reach it.
          <span className="font-medium"> Pressure is estimated from tickets — not a direct congestion measurement.</span>{" "}
          {q?.source === "rerank-cache"
            ? `Updated from the hourly cache${q?.last_rerank ? ` · ${relativeTime(new Date(q.last_rerank * 1000).toISOString())}` : ""}.`
            : "Updated just now."}{" "}
          Area-level only — never per officer.
        </p>
      </CardContent>
    </Card>
  );
}
