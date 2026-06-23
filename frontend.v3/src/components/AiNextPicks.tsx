import { useEffect, useMemo, useState } from "react";
import { Brain, Target, Compass, MapPin, RefreshCw } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getDispatchQueue } from "@/lib/api";
import { picColor } from "@/lib/format";
import { relativeTime } from "@/lib/time";
import { cellLabel } from "@/lib/signals";
import type { DispatchQueue, RerankRow, When } from "@/lib/types";

const TIER_VARIANT: Record<string, "destructive" | "warning" | "secondary"> = {
  P1: "destructive",
  P2: "warning",
  P3: "secondary",
  P4: "secondary",
};

function PickRow({ r, onFocus }: { r: RerankRow; onFocus: (lat: number, lon: number, h3?: string) => void }) {
  return (
    <div className="flex items-center gap-2 rounded-lg border bg-card p-2">
      <span
        className="num inline-flex h-7 w-9 shrink-0 items-center justify-center rounded-md text-xs font-bold text-white"
        style={{ background: picColor(r.rerank_score) }}
      >
        {Math.round(r.rerank_score)}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <Badge variant={TIER_VARIANT[r.dispatch_tier]} className="px-1.5 py-0">
            {r.dispatch_tier}
          </Badge>
          <span className="truncate text-[11px] text-muted-foreground">{cellLabel(r)}</span>
        </div>
        <div className="truncate text-[11px] text-muted-foreground">{r.reason_codes[0] ?? "top modeled priority"}</div>
      </div>
      <Button size="icon" variant="ghost" className="h-7 w-7 shrink-0" title="Open details" onClick={() => onFocus(r.lat, r.lon, r.h3_r10)}>
        <MapPin className="h-3.5 w-3.5" />
      </Button>
    </div>
  );
}

// Explore-vs-exploit next picks from the M4 dispatch reranker / bandit signals:
//  · EXPLOIT = known, high-pressure hotspots (best return on a sure thing)
//  · EXPLORE = under-observed / emerging blind-spot candidates (discovery value)
export function AiNextPicks({
  station,
  when = "now",
  hour,
  onFocus,
  title = "AI next picks",
}: {
  station?: string | null;
  when?: When;
  hour?: number;
  onFocus: (lat: number, lon: number, h3?: string) => void;
  title?: string;
}) {
  const [q, setQ] = useState<DispatchQueue | null>(null);
  const [loading, setLoading] = useState(false);

  function load() {
    setLoading(true);
    getDispatchQueue(station ?? undefined, when, hour)
      .then(setQ)
      .finally(() => setLoading(false));
  }
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [station, when, hour]);

  const { exploit, explore } = useMemo(() => {
    const rows = q?.queue ?? [];
    const isExplore = (r: RerankRow) => r.under_observed_candidate || r.emerging;
    const explore = rows.filter(isExplore).sort((a, b) => b.rerank_score - a.rerank_score).slice(0, 6);
    const exploit = rows.filter((r) => !isExplore(r)).sort((a, b) => b.rerank_score - a.rerank_score).slice(0, 6);
    return { exploit, explore };
  }, [q]);

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2 text-base">
            <Brain className="h-4 w-4 text-primary" /> {title}
          </CardTitle>
          <div className="flex items-center gap-2">
            {q?.last_rerank && <span className="text-[11px] text-muted-foreground">updated {relativeTime(new Date(q.last_rerank * 1000).toISOString())}</span>}
            <Button size="sm" variant="outline" onClick={load} disabled={loading}>
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-[12px] text-muted-foreground">
          Explore vs exploit balances <span className="font-medium text-foreground">known hotspots</span> with{" "}
          <span className="font-medium text-foreground">under-observed zones</span> — so patrols both cover sure things and discover blind spots.
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-2">
            <div className="flex items-center gap-1.5 text-xs font-semibold">
              <Target className="h-3.5 w-3.5 text-destructive" /> Exploit · known hotspots
            </div>
            {exploit.length ? exploit.map((r) => <PickRow key={r.id} r={r} onFocus={onFocus} />) : <Empty loading={loading} />}
          </div>
          <div className="space-y-2">
            <div className="flex items-center gap-1.5 text-xs font-semibold">
              <Compass className="h-3.5 w-3.5 text-[hsl(var(--modeled))]" /> Explore · under-observed
            </div>
            {explore.length ? explore.map((r) => <PickRow key={r.id} r={r} onFocus={onFocus} />) : <Empty loading={loading} label="No under-observed candidates in range." />}
          </div>
        </div>
        <p className="text-[11px] leading-tight text-muted-foreground">
          Lens: {q?.when ?? when} · {q?.dow ?? "—"} · {String(q?.hour ?? hour ?? "—").padStart(2, "0")}:00. Picks come from the M4 dispatch reranker (forecast · pressure · under-observed · congestion · reachability). Pressure is
          MODELED from tickets — never measured congestion. Cell/station-level only; never per officer.
        </p>
      </CardContent>
    </Card>
  );
}

function Empty({ loading, label = "No cells in range." }: { loading: boolean; label?: string }) {
  return <div className="rounded-lg border border-dashed p-3 text-center text-[12px] text-muted-foreground">{loading ? "Loading…" : label}</div>;
}
