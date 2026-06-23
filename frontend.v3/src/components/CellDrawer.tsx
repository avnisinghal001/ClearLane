import { type ReactNode } from "react";
import { QRCodeSVG } from "qrcode.react";
import { MapPin, TrendingUp, Navigation, Copy, ShieldCheck, Gauge } from "lucide-react";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { SourceBadge } from "./SourceBadge";
import { BarSpark } from "./Sparkline";
import { toast } from "./toast";
import { DOW } from "@/lib/time";
import { num, severityLabel, mapsUrl } from "@/lib/format";
import { isBlindSpot, intervention, priorityLabel, whyFlagged, ROAD_CLASS_LABEL } from "@/lib/signals";
import type { Cell } from "@/lib/types";

type Audience = "citizen" | "police";

function Kv({ k, v }: { k: string; v: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-2 border-b py-1.5 last:border-b-0">
      <span className="text-[11px] text-muted-foreground">{k}</span>
      <span className="num text-[12px] font-medium">{v}</span>
    </div>
  );
}

export function CellDrawer({
  cell,
  side = "right",
  audience = "police",
  onClose,
  children,
}: {
  cell: Cell | null;
  cells?: Cell[]; // accepted for API compatibility; the simplified card no longer needs the city set
  side?: "right" | "bottom";
  audience?: Audience;
  onClose: () => void;
  children?: ReactNode;
}) {
  const prio = cell ? priorityLabel(cell) : null;
  const rec = cell ? intervention(cell) : null;
  const chips = cell ? whyFlagged(cell) : [];
  const blind = cell ? isBlindSpot(cell) : false;
  const monitorOnly = rec?.action === "Monitor";
  const roadLabel = cell?.road_class ? ROAD_CLASS_LABEL[cell.road_class] ?? cell.road_class : null;

  return (
    <Sheet open={Boolean(cell)} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side={side} className="w-full p-0 sm:max-w-md">
        {cell && prio && rec && (
          <div className="flex h-full flex-col">
            <SheetHeader className="border-b">
              <div className="flex items-start justify-between gap-2 pr-6">
                <div className="min-w-0">
                  <SheetTitle className="flex items-center gap-2">
                    <MapPin className="h-4 w-4 shrink-0 text-primary" />
                    <span className="truncate">{cell.police_station || "This location"}</span>
                  </SheetTitle>
                  {roadLabel && <div className="mt-0.5 pl-6 text-[12px] text-muted-foreground">{roadLabel}</div>}
                </div>
                <span
                  className="flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold text-white"
                  style={{ background: prio.color }}
                >
                  {prio.word}
                  {audience === "police" && <span className="opacity-80">· {prio.tier}</span>}
                </span>
              </div>
              <div className="flex flex-wrap gap-2 pt-1">
                <a href={mapsUrl(cell.lat, cell.lon)} target="_blank" rel="noreferrer">
                  <Button size="sm" className="gap-1.5">
                    <Navigation className="h-3.5 w-3.5" /> Open in Maps
                  </Button>
                </a>
              </div>
            </SheetHeader>

            <div className="flex-1 space-y-3 overflow-y-auto p-5">
              {/* Why it's flagged — plain priority + human chips */}
              <div className="rounded-xl border p-3">
                <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  <Gauge className="h-3.5 w-3.5" /> Why it's flagged
                </div>
                <p className="mt-1.5 text-sm">{prio.blurb}</p>
                {chips.length > 0 && (
                  <div className="mt-2.5 flex flex-wrap gap-1.5">
                    {chips.map((c) => (
                      <Badge key={c.label} variant={c.tone} className="font-medium">
                        {c.label}
                      </Badge>
                    ))}
                  </div>
                )}
              </div>

              {/* What to do — the recommendation */}
              <div className="rounded-xl border border-primary/30 bg-primary/5 p-3">
                <div className="flex items-start gap-2">
                  <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                  <div>
                    <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      {audience === "citizen" ? "What the police can do here" : "Recommended action"}
                    </div>
                    <div className="mt-0.5 text-sm font-semibold">
                      {monitorOnly ? "Routine monitoring" : rec.action}
                    </div>
                    {!monitorOnly && rec.window !== "—" && (
                      <div className="mt-0.5 text-[12px] text-muted-foreground">{rec.window}</div>
                    )}
                  </div>
                </div>
                {blind && (
                  <div className="mt-2 flex items-start gap-1.5 text-[12px] text-amber-600">
                    <span className="mt-1 inline-block h-2.5 w-2.5 shrink-0 rounded-full border border-dashed border-amber-600" />
                    Busy in the evening but lightly patrolled — a good spot for an evening check.
                  </div>
                )}
              </div>

              {/* Congestion — one concise line with the honest provenance badge */}
              <div className="flex items-center justify-between gap-2 rounded-xl border p-3">
                <div>
                  <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Typical congestion</div>
                  <div className="mt-0.5 text-sm font-semibold">{severityLabel(cell.congestion_severity)}</div>
                </div>
                <div className="flex flex-col items-end gap-1">
                  <SourceBadge source={cell.congestion_source} />
                  <span className="text-[10px] text-muted-foreground">estimated, not measured</span>
                </div>
              </div>

              {/* QR to Google Maps (generated locally, no network) */}
              <div className="flex items-center gap-3 rounded-xl border p-3">
                <div className="rounded-md bg-white p-1.5">
                  <QRCodeSVG value={mapsUrl(cell.lat, cell.lon)} size={76} level="M" />
                </div>
                <span className="text-[12px] leading-tight text-muted-foreground">
                  Scan to open this exact spot in Google Maps on your phone.
                </span>
              </div>

              {/* Everything technical lives here, collapsed by default */}
              <Accordion type="single" collapsible className="rounded-xl border px-3">
                <AccordionItem value="details" className="border-b-0">
                  <AccordionTrigger>Details</AccordionTrigger>
                  <AccordionContent className="space-y-3">
                    <div className="rounded-lg border bg-muted/20 p-2.5">
                      <Kv k="Area" v={cell.police_station || "—"} />
                      {roadLabel && <Kv k="Road type" v={roadLabel} />}
                      <Kv k="Coordinates" v={`${cell.lat.toFixed(5)}, ${cell.lon.toFixed(5)}`} />
                      <div className="flex items-center justify-between gap-2 pt-1.5">
                        <span className="text-[11px] text-muted-foreground">Cell id</span>
                        <button
                          className="flex items-center gap-1 font-mono text-[11px] text-muted-foreground hover:text-foreground"
                          onClick={() => {
                            navigator.clipboard?.writeText(cell.h3_r10);
                            toast("Cell id copied", { tone: "info" });
                          }}
                        >
                          {cell.h3_r10} <Copy className="h-3 w-3" />
                        </button>
                      </div>
                    </div>

                    {cell.dow_curve && (
                      <div>
                        <div className="mb-1 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                          <TrendingUp className="h-3.5 w-3.5" /> Typical week
                        </div>
                        <BarSpark values={cell.dow_curve} labels={DOW} height={50} />
                        <div className="mt-1 text-[11px] text-muted-foreground">
                          Expected violations per day · busiest {cell.peak_dow ?? "—"} · {num(cell.weekly_expected, 0)}/week.
                          A day-of-week pattern (modeled, not measured congestion).
                        </div>
                      </div>
                    )}

                    {/* the three-number separation kept intact for transparency */}
                    <div>
                      <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">How the priority is built</div>
                      <div className="grid grid-cols-3 gap-2 text-center">
                        <div className="rounded-lg border bg-muted/20 p-2">
                          <div className="num text-base font-bold">{Math.round(cell.pic_score)}</div>
                          <div className="text-[10px] text-muted-foreground">history</div>
                        </div>
                        <div className="rounded-lg border bg-muted/20 p-2">
                          <div className="num text-base font-bold text-primary">+{Math.round(cell.live_adjustment ?? 0)}</div>
                          <div className="text-[10px] text-muted-foreground">live boost</div>
                        </div>
                        <div className="rounded-lg border bg-muted/20 p-2">
                          <div className="num text-base font-bold">{Math.round(cell.operational_priority ?? cell.pic_score)}</div>
                          <div className="text-[10px] text-muted-foreground">now</div>
                        </div>
                      </div>
                      <p className="mt-1.5 text-[11px] leading-tight text-muted-foreground">
                        The live boost is a short, decaying response to fresh reports — it never rewrites the historical score.
                      </p>
                    </div>
                  </AccordionContent>
                </AccordionItem>
              </Accordion>
            </div>

            {children && <div className="border-t p-4">{children}</div>}
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
