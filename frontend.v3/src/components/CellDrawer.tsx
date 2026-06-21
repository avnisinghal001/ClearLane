import { useMemo, type ReactNode } from "react";
import { QRCodeSVG } from "qrcode.react";
import { MapPin, TrendingUp, AlertTriangle, ExternalLink, Copy, Activity } from "lucide-react";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { SourceBadge } from "./SourceBadge";
import { BarSpark } from "./Sparkline";
import { toast } from "./toast";
import { DOW } from "@/lib/time";
import { num, severityLabel, mapsUrl } from "@/lib/format";
import {
  cellTier, tierColor, isBlindSpot, flowImpactTable, flowImpact, intervention,
  pressureScore, recurrenceScore, emergenceScore, priorityScore, ROAD_CLASS_LABEL,
} from "@/lib/signals";
import type { Cell } from "@/lib/types";

function Dial({ label, value, color }: { label: string; value: ReactNode; color?: string }) {
  return (
    <div className="rounded-lg border bg-muted/30 p-2.5 text-center">
      <div className="num text-xl font-bold leading-none" style={color ? { color } : undefined}>
        {value}
      </div>
      <div className="mt-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground">{label}</div>
    </div>
  );
}

function Kv({ k, v }: { k: string; v: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-2 border-b py-1 last:border-b-0">
      <span className="text-[11px] text-muted-foreground">{k}</span>
      <span className="num text-[12px] font-medium">{v}</span>
    </div>
  );
}

const km = (m: number | null | undefined) => (m == null ? "—" : m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${Math.round(m)} m`);

export function CellDrawer({
  cell,
  cells,
  side = "right",
  onClose,
  children,
}: {
  cell: Cell | null;
  cells?: Cell[]; // full set for the flow-impact rank/normalization (modeled proxy)
  side?: "right" | "bottom";
  onClose: () => void;
  children?: ReactNode;
}) {
  // flow-impact table over the supplied cells (rank + normalized score), memoized.
  const flowTable = useMemo(() => (cells && cells.length ? flowImpactTable(cells) : null), [cells]);
  const fi = cell ? flowTable?.get(cell.h3_r10) ?? { ...flowImpact(cell), score: pressureScore(cell), rank: 0 } : null;
  const tier = cell ? cellTier(cell) : "P4";
  const rec = cell ? intervention(cell) : null;
  const blind = cell ? isBlindSpot(cell) : false;

  return (
    <Sheet open={Boolean(cell)} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side={side} className="w-full p-0 sm:max-w-md">
        {cell && fi && rec && (
          <div className="flex h-full flex-col">
            <SheetHeader className="border-b">
              <div className="flex items-center justify-between gap-2 pr-6">
                <SheetTitle className="flex items-center gap-2">
                  <MapPin className="h-4 w-4 text-primary" />
                  {cell.police_station || "Unassigned area"}
                </SheetTitle>
                <div className="flex items-center gap-1.5">
                  <Badge style={{ background: tierColor(tier), color: "#fff" }}>{tier}</Badge>
                  {cell.emerging && (
                    <Badge variant="warning" className="gap-1">
                      <AlertTriangle className="h-3 w-3" /> Emerging
                    </Badge>
                  )}
                </div>
              </div>
              <div className="font-mono text-[11px] text-muted-foreground">
                {cell.h3_r10} · {cell.lat.toFixed(5)}, {cell.lon.toFixed(5)}
              </div>
              <div className="flex flex-wrap gap-2 pt-1">
                <a href={mapsUrl(cell.lat, cell.lon)} target="_blank" rel="noreferrer">
                  <Button size="sm" variant="outline" className="gap-1.5">
                    <ExternalLink className="h-3.5 w-3.5" /> Google Maps
                  </Button>
                </a>
                <Button
                  size="sm"
                  variant="outline"
                  className="gap-1.5"
                  onClick={() => {
                    navigator.clipboard?.writeText(`${cell.lat},${cell.lon}`);
                    toast("Coordinates copied", { tone: "info" });
                  }}
                >
                  <Copy className="h-3.5 w-3.5" /> Copy coords
                </Button>
              </div>
            </SheetHeader>

            <div className="flex-1 space-y-4 overflow-y-auto p-5">
              {/* Pressure / Recurrence / Emergence / Priority */}
              <div className="grid grid-cols-4 gap-2">
                <Dial label="Pressure" value={pressureScore(cell)} />
                <Dial label="Recurrence" value={recurrenceScore(cell)} />
                <Dial label="Emergence" value={emergenceScore(cell)} />
                <Dial label="Priority" value={priorityScore(cell)} color={tierColor(tier)} />
              </div>

              {/* intervention recommendation */}
              <div className="rounded-lg border border-primary/30 bg-primary/5 p-3">
                <div className="flex items-start gap-2">
                  <Activity className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                  <div>
                    <div className="text-sm font-semibold">{rec.action}</div>
                    <div className="mt-0.5 text-[11px] text-muted-foreground">Window: {rec.window}</div>
                  </div>
                </div>
                {blind && (
                  <div className="mt-2 flex items-center gap-1.5 text-[11px] text-amber-600">
                    <span className="inline-block h-2.5 w-2.5 rounded-full border border-dashed border-amber-600" />
                    Evening blind spot — high priority but under-observed (modeled, not measured).
                  </div>
                )}
              </div>

              {/* three-number separation (historical / live / operational) */}
              <div className="rounded-lg border p-3">
                <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Priority breakdown</div>
                <div className="grid grid-cols-3 gap-2 text-center">
                  <div>
                    <div className="num text-lg font-bold">{Math.round(cell.pic_score)}</div>
                    <div className="text-[10px] text-muted-foreground">historical</div>
                  </div>
                  <div>
                    <div className="num text-lg font-bold text-primary">+{Math.round(cell.live_adjustment ?? 0)}</div>
                    <div className="text-[10px] text-muted-foreground">live boost</div>
                  </div>
                  <div>
                    <div className="num text-lg font-bold">{Math.round(cell.operational_priority ?? cell.pic_score)}</div>
                    <div className="text-[10px] text-muted-foreground">operational</div>
                  </div>
                </div>
                <p className="mt-2 text-[11px] leading-tight text-muted-foreground">
                  Live boost is a transparent, decaying response to fresh reports — it never edits the historical model score.
                </p>
              </div>

              {/* Carriageway impact — modeled flow-impact proxy */}
              <div>
                <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Carriageway impact (flow-impact proxy)</div>
                <div className="grid grid-cols-3 gap-2">
                  <Dial label="Flow impact" value={Math.round(fi.score)} color="hsl(var(--modeled))" />
                  <Dial label="Context mult." value={`×${fi.multiplier.toFixed(2)}`} />
                  <Dial label="Flow rank" value={fi.rank ? `#${fi.rank}` : "—"} />
                </div>
                <div className="mt-2 rounded-lg border bg-muted/20 p-2.5">
                  <Kv k="Junction criticality" v={`${Math.round(fi.junction * 100)}%`} />
                  <Kv k="Road class" v={`${ROAD_CLASS_LABEL[fi.road_class] ?? fi.road_class} (${fi.road_weight})`} />
                  <Kv k="Nearest metro" v={km(fi.dist_metro_m)} />
                  <Kv k="Nearest commercial hub" v={km(fi.dist_commercial_m)} />
                  <div className="flex items-center justify-between gap-2 py-1">
                    <span className="text-[11px] text-muted-foreground">Congestion severity</span>
                    <span className="flex items-center gap-1.5">
                      <span className="num text-[12px] font-medium">{severityLabel(cell.congestion_severity)}</span>
                      <SourceBadge source={cell.congestion_source} />
                    </span>
                  </div>
                </div>
                <p className="mt-1.5 text-[11px] leading-tight text-muted-foreground">
                  Obstruction pressure scaled by static road context (junction tag, road class, metro/commercial proximity).
                  A <b>modeled proxy for movement disruption — not a measurement of congestion</b> (the data has no flow/speed signal).
                </p>
              </div>

              {/* QR to Google Maps (generated locally, no network) */}
              <div className="flex items-center gap-3 rounded-lg border p-3">
                <div className="rounded-md bg-white p-1.5">
                  <QRCodeSVG value={mapsUrl(cell.lat, cell.lon)} size={84} level="M" />
                </div>
                <span className="text-[11px] leading-tight text-muted-foreground">
                  Scan to open this exact location in Google Maps on a phone (generated locally, no network).
                </span>
              </div>

              {cell.dow_curve && (
                <div>
                  <div className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    <TrendingUp className="h-3.5 w-3.5" /> Weekly forecast pattern
                  </div>
                  <BarSpark values={cell.dow_curve} labels={DOW} height={56} />
                  <div className="mt-1 text-[11px] text-muted-foreground">
                    Expected violations/day · peak {cell.peak_dow ?? "—"} · {num(cell.weekly_expected, 0)}/week. Forecast propensity — modeled, not measured congestion.
                  </div>
                </div>
              )}

              {cell.emerging && (
                <div className="rounded-lg border border-[hsl(var(--warning))]/40 bg-[hsl(var(--warning))]/10 p-3 text-sm">
                  <b>Emerging hotspot.</b> Recent activity drifted {cell.drift_z?.toFixed(1)}σ above its baseline
                  {cell.e_lambda != null ? ` (≈${cell.e_lambda.toFixed(2)} violations/day expected).` : "."}
                </div>
              )}
            </div>

            {children && <div className="border-t p-4">{children}</div>}
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
