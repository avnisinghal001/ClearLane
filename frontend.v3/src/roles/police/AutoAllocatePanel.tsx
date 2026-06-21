import { useCallback, useEffect, useMemo, useState } from "react";
import { Layers, RefreshCw, Minus, Plus, AlertTriangle, RotateCcw } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { autoAllocate } from "@/lib/api";
import { cellTier, tierColor } from "@/lib/signals";
import type { AllocZone, AutoAllocation, Cell, Officer } from "@/lib/types";

const TIER_WEIGHT: Record<string, number> = { P1: 1.0, P2: 0.66, P3: 0.4, P4: 0.2 };
const SHIFT_HOURS = 6;
const TPOH = 4.0;

// Largest-remainder (Hamilton) apportionment so the parts sum back to `total`.
function largestRemainder(weights: number[], total: number): number[] {
  const n = weights.length;
  if (!n || total <= 0) return new Array(n).fill(0);
  const wsum = weights.reduce((a, b) => a + b, 0) || 1;
  const raw = weights.map((w) => (total * w) / wsum);
  const base = raw.map((x) => Math.floor(x));
  let rem = total - base.reduce((a, b) => a + b, 0);
  const order = raw.map((x, i) => [x - base[i], i] as [number, number]).sort((a, b) => b[0] - a[0]);
  for (let i = 0; rem > 0 && n > 0; i++, rem--) base[order[i % n][1]]++;
  return base;
}

// Offline compose (when the live force endpoint is unreachable): zones = the station's
// top priority cells, weighted by tier × pressure; officers = on-shift roster count.
function composeOffline(cells: Cell[], officers: Officer[], shift: string | null, stationName: string, slug: string): AutoAllocation {
  const onShift = officers.filter((o) => o.status !== "off" && (!shift || o.shift === shift)).length;
  const zonesRaw = cells
    .filter((c) => (c.pic_score ?? 0) > 0)
    .sort((a, b) => (b.pic_score ?? 0) - (a.pic_score ?? 0))
    .slice(0, 14)
    .map((c) => {
      const tier = cellTier(c);
      return { cell: c.h3_r10, lat: c.lat, lon: c.lon, tier, rerank_score: Math.round(c.pic_score ?? 0), pressure: Math.round(c.pic_score ?? 0), road_class: c.road_class, reason_codes: [] as string[], weight: TIER_WEIGHT[tier] * Math.max((c.pic_score ?? 0) / 100, 0.01) };
    });
  const counts = largestRemainder(zonesRaw.map((z) => z.weight), onShift);
  const totalW = zonesRaw.reduce((a, z) => a + z.weight, 0) || 1;
  const allocations: AllocZone[] = zonesRaw.map((z, i) => ({ ...z, officers: counts[i], share_pct: Math.round((1000 * z.weight) / totalW) / 10 }));
  const expected = cells.reduce((a, c) => a + (c.weekly_expected ?? 0), 0) / 7 * (SHIFT_HOURS / 24);
  const recommended = Math.max(1, Math.ceil(expected / (TPOH * SHIFT_HOURS)));
  return {
    station: slug, station_name: stationName, shift, shift_label: shift ?? "All shifts",
    on_shift_officers: onShift, recommended_officers: recommended, deficit: Math.max(0, recommended - onShift),
    short_staffed: recommended > onShift, tickets_per_officer_hour: TPOH, shift_hours: SHIFT_HOURS,
    expected_shift_tickets: Math.round(expected * 10) / 10, n_zones: allocations.length, allocations, overflow: [],
    method: "Offline compose: top priority cells weighted by tier × MODELED pressure (live backend unavailable).",
    honesty: "Zones ranked by MODELED pressure (never measured congestion); allocation is operational planning — never a per-officer score.",
  };
}

// Auto-allocate (priority × area): distribute the station's on-shift officers across
// its priority zones weighted by tier × MODELED rerank pressure. Live -> the backend
// heuristic; offline -> composed from the station's cells. Manual override: nudge a
// zone's officer count ± and reset.
export function AutoAllocatePanel({
  slug,
  stationName,
  cells,
  officers,
  shiftOrder,
  shiftLabels,
}: {
  slug: string;
  stationName: string;
  cells: Cell[];
  officers: Officer[];
  shiftOrder: string[];
  shiftLabels: Record<string, string>;
}) {
  const [shift, setShift] = useState<string | "all">("all");
  const [alloc, setAlloc] = useState<AutoAllocation | null>(null);
  const [loading, setLoading] = useState(false);
  const [override, setOverride] = useState<Record<string, number>>({});

  const load = useCallback(() => {
    setLoading(true);
    setOverride({});
    const sh = shift === "all" ? null : shift;
    autoAllocate(slug, sh)
      .then((live) => setAlloc(live ?? composeOffline(cells, officers, sh, stationName, slug)))
      .finally(() => setLoading(false));
  }, [slug, shift, cells, officers, stationName]);

  useEffect(() => load(), [load]);

  const totalAssigned = useMemo(() => {
    if (!alloc) return 0;
    return alloc.allocations.reduce((a, z) => a + (override[z.cell] ?? z.officers), 0);
  }, [alloc, override]);

  function nudge(cell: string, base: number, d: number) {
    setOverride((o) => ({ ...o, [cell]: Math.max(0, (o[cell] ?? base) + d) }));
  }
  const dirty = Object.keys(override).length > 0;

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2 text-base">
            <Layers className="h-4 w-4 text-primary" /> Auto-allocate · priority × area
          </CardTitle>
          <div className="flex items-center gap-1.5">
            <select aria-label="Shift" value={shift} onChange={(e) => setShift(e.target.value)} className="h-8 rounded-md border bg-background px-2 text-xs">
              <option value="all">All shifts</option>
              {shiftOrder.map((s) => (
                <option key={s} value={s}>
                  {s} · {shiftLabels[s] ?? s}
                </option>
              ))}
            </select>
            <Button size="icon" variant="outline" onClick={load} disabled={loading} title="Recompute">
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* staffing heuristic summary */}
        {alloc && (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <Mini label="On shift" value={alloc.on_shift_officers} />
            <Mini label="Recommended" value={alloc.recommended_officers} />
            <Mini label="Assigned" value={totalAssigned} sub={dirty ? "manual override" : "auto"} />
            <Mini label="Zones" value={alloc.n_zones} />
          </div>
        )}

        {alloc?.short_staffed && (
          <div className="flex items-start gap-2 rounded-lg border border-[hsl(var(--warning))]/40 bg-[hsl(var(--warning))]/10 px-3 py-2 text-[12px]">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-[hsl(var(--warning))]" />
            <div>
              <b>Short of recommended strength</b> by {alloc.deficit} on this shift (≈{alloc.expected_shift_tickets} expected verifications · {alloc.tickets_per_officer_hour}/officer/hr × {alloc.shift_hours}h).
              {alloc.overflow.length > 0 && (
                <div className="mt-1">
                  Nearest stations that could lend (local-first overflow):{" "}
                  {alloc.overflow.map((o) => (
                    <span key={o.station} className="font-medium">
                      {o.station_name} (+{o.can_lend}, {o.distance_km} km){" "}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {/* per-zone apportionment + manual override */}
        <div className="space-y-1.5">
          {(alloc?.allocations ?? []).map((z) => {
            const n = override[z.cell] ?? z.officers;
            return (
              <div key={z.cell} className="flex items-center gap-2 rounded-lg border bg-card px-2.5 py-1.5">
                <span className="inline-flex h-6 w-7 items-center justify-center rounded text-[11px] font-bold text-white" style={{ background: tierColor(z.tier) }}>
                  {z.tier}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="num truncate text-xs text-muted-foreground">{z.cell.slice(0, 10)}…</div>
                  <div className="text-[11px] text-muted-foreground">
                    PIC {Math.round(z.pressure)} · {z.road_class ?? "—"} · {z.share_pct}% share
                  </div>
                </div>
                <div className="flex items-center gap-1">
                  <Button size="icon" variant="ghost" className="h-6 w-6" onClick={() => nudge(z.cell, z.officers, -1)} disabled={n <= 0} title="Fewer officers">
                    <Minus className="h-3.5 w-3.5" />
                  </Button>
                  <span className="num w-5 text-center text-sm font-bold">{n}</span>
                  <Button size="icon" variant="ghost" className="h-6 w-6" onClick={() => nudge(z.cell, z.officers, 1)} title="More officers">
                    <Plus className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
            );
          })}
          {alloc && !alloc.allocations.length && <div className="text-sm text-muted-foreground">No priority zones for this station yet.</div>}
        </div>

        {dirty && (
          <Button size="sm" variant="outline" className="gap-1.5" onClick={() => setOverride({})}>
            <RotateCcw className="h-3.5 w-3.5" /> Reset to auto
          </Button>
        )}

        <p className="text-[11px] leading-tight text-muted-foreground">
          Officers apportioned across priority zones by tier (P1&gt;P2&gt;P3&gt;P4) × MODELED rerank pressure. Dispatch is local-first; overflow borrows
          from the nearest stations only when short. {alloc?.station_name ? "" : ""}Operational planning — never a per-officer score.
        </p>
      </CardContent>
    </Card>
  );
}

function Mini({ label, value, sub }: { label: string; value: React.ReactNode; sub?: string }) {
  return (
    <div className="rounded-lg border bg-muted/30 p-2">
      <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="num text-lg font-bold leading-tight">{value}</div>
      {sub && <div className="text-[10px] text-muted-foreground">{sub}</div>}
    </div>
  );
}
