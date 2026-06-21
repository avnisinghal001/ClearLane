import type { ReactNode } from "react";
import { MapPin, TrendingUp, AlertTriangle } from "lucide-react";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { SourceBadge } from "./SourceBadge";
import { BarSpark } from "./Sparkline";
import { DOW } from "@/lib/time";
import { num, severityLabel } from "@/lib/format";
import type { Cell } from "@/lib/types";

function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="rounded-lg border bg-muted/30 p-2.5">
      <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="num mt-0.5 text-lg font-semibold leading-none">{value}</div>
      {hint && <div className="mt-0.5 text-[11px] text-muted-foreground">{hint}</div>}
    </div>
  );
}

export function CellDrawer({
  cell,
  side = "right",
  onClose,
  children,
}: {
  cell: Cell | null;
  side?: "right" | "bottom";
  onClose: () => void;
  children?: ReactNode;
}) {
  return (
    <Sheet open={Boolean(cell)} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side={side} className="w-full p-0 sm:max-w-md">
        {cell && (
          <div className="flex h-full flex-col">
            <SheetHeader className="border-b">
              <div className="flex items-center justify-between gap-2 pr-6">
                <SheetTitle className="flex items-center gap-2">
                  <MapPin className="h-4 w-4 text-primary" />
                  {cell.police_station || "Unassigned area"}
                </SheetTitle>
                {cell.emerging && (
                  <Badge variant="warning" className="gap-1">
                    <AlertTriangle className="h-3 w-3" /> Emerging
                  </Badge>
                )}
              </div>
              <div className="font-mono text-[11px] text-muted-foreground">{cell.h3_r10}</div>
            </SheetHeader>

            <div className="flex-1 space-y-4 overflow-y-auto p-5">
              <div className="grid grid-cols-2 gap-2">
                <Stat label="PIC score" value={Math.round(cell.pic_score)} hint="parking-induced congestion" />
                <Stat label="Intensity" value={Math.round(cell.intensity)} hint="bias-corrected" />
                <div className="rounded-lg border bg-muted/30 p-2.5">
                  <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Severity</div>
                  <div className="mt-0.5 flex items-center gap-2">
                    <span className="text-lg font-semibold leading-none">{severityLabel(cell.congestion_severity)}</span>
                    <SourceBadge source={cell.congestion_source} />
                  </div>
                  <div className="mt-0.5 text-[11px] text-muted-foreground">{(cell.congestion_severity * 100).toFixed(0)}% travel-time ratio</div>
                </div>
                <Stat label="Road class" value={<span className="text-sm">{cell.road_class ?? "—"}</span>} hint={`${num(cell.count)} tickets recorded`} />
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

              {cell.dow_curve && (
                <div>
                  <div className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    <TrendingUp className="h-3.5 w-3.5" /> Weekly forecast pattern
                  </div>
                  <BarSpark values={cell.dow_curve} labels={DOW} height={56} />
                  <div className="mt-1 text-[11px] text-muted-foreground">
                    Expected violations/day · peak {cell.peak_dow ?? "—"} · {num(cell.weekly_expected, 0)}/week. Modeled, not measured congestion.
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
