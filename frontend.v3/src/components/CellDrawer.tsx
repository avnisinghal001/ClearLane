import { type ReactNode, useEffect, useState } from "react";
import { MapPin, Navigation, ShieldCheck, Repeat, Clock, Ban, Car } from "lucide-react";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { num, mapsUrl } from "@/lib/format";
import { getCellDetail } from "@/lib/api";
import { isBlindSpot, intervention, priorityLabel, pressureScore, recurrenceScore, emergenceScore, priorityScore, ROAD_CLASS_LABEL } from "@/lib/signals";
import type { Cell, CellDetail, MixItem } from "@/lib/types";

type Audience = "citizen" | "police" | "govt";

function SectionTitle({ icon, children }: { icon: ReactNode; children: ReactNode }) {
  return (
    <h3 className="flex items-center gap-1.5 text-sm font-bold">
      {icon}
      {children}
    </h3>
  );
}

// A single KPI "info card" — big number out of 100, plain label + one-word hint.
// Union across all roles (citizen / police / govt see the same cards).
function InfoCard({ value, label, hint, tone = "default" }: { value: ReactNode; label: string; hint?: string; tone?: "default" | "primary" | "warning" }) {
  const ring = tone === "warning" ? "border-amber-500/40 bg-amber-500/5" : tone === "primary" ? "border-primary/40 bg-primary/5" : "border-border bg-muted/30";
  const text = tone === "warning" ? "text-amber-600" : tone === "primary" ? "text-primary" : "text-foreground";
  return (
    <div className={`rounded-xl border ${ring} p-2.5 text-center`}>
      <div className={`num text-xl font-bold leading-none ${text}`}>{value}</div>
      <div className="mt-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{label}</div>
      {hint && <div className="text-[9px] leading-tight text-muted-foreground/80">{hint}</div>}
    </div>
  );
}

// Themed horizontal bars for the "main problems" / "vehicles" lists.
function MixBars({ items }: { items: MixItem[] }) {
  const max = Math.max(1, ...items.map((i) => i.count));
  return (
    <div className="space-y-1.5">
      {items.map((i) => (
        <div key={i.name}>
          <div className="flex items-center justify-between gap-2 text-[12px]">
            <span className="truncate capitalize">{i.name.toLowerCase()}</span>
            <span className="num text-muted-foreground">{i.count}</span>
          </div>
          <div className="mt-0.5 h-1.5 overflow-hidden rounded-full bg-muted">
            <div className="h-full rounded-full bg-primary/70" style={{ width: `${(100 * i.count) / max}%` }} />
          </div>
        </div>
      ))}
    </div>
  );
}

// Hour-of-day bars, with the evening rush (5–9 PM) in amber.
function HourBars({ values, height = 56 }: { values: number[]; height?: number }) {
  const max = Math.max(1, ...values);
  return (
    <div className="flex items-end gap-px" style={{ height }}>
      {values.map((v, h) => {
        const evening = h >= 17 && h < 21;
        return (
          <div
            key={h}
            className={`flex-1 rounded-sm ${evening ? "bg-amber-500" : "bg-primary/40"}`}
            style={{ height: `${Math.max(2, (v / max) * height)}px` }}
            title={`${String(h).padStart(2, "0")}:00 — ${v}`}
          />
        );
      })}
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
  cells?: Cell[]; // kept for call-site compatibility (no longer used)
  side?: "right" | "bottom";
  audience?: Audience; // kept for call-site compatibility; modal is now identical for all roles
  onClose: () => void;
  children?: ReactNode;
}) {
  const [detail, setDetail] = useState<CellDetail | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!cell) {
      setDetail(null);
      return;
    }
    let alive = true;
    setDetail(null);
    setLoading(true);
    getCellDetail(cell.h3_r10)
      .then((d) => alive && setDetail(d))
      .catch(() => alive && setDetail(null))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [cell]);

  const prio = cell ? priorityLabel(cell) : null;
  const rec = cell ? intervention(cell) : null;
  const blind = cell ? isBlindSpot(cell) : false;
  const monitorOnly = rec?.action === "Monitor";
  const roadLabel = cell?.road_class ? ROAD_CLASS_LABEL[cell.road_class] ?? cell.road_class : null;

  const hist = detail?.historical ?? null;
  const live = detail?.live ?? null;
  const repeatPct = hist?.repeat_share != null ? Math.round(hist.repeat_share * 100)
    : live?.repeat_share != null ? Math.round(live.repeat_share * 100) : null;
  const habitual = repeatPct != null && repeatPct >= 45;
  // union KPI cards (same for citizen / police / govt) — each 0..100
  const kPriority = cell ? priorityScore(cell) : 0;
  const kPressure = cell ? pressureScore(cell) : 0;
  const kRepeat = cell ? recurrenceScore(cell) : 0;
  const kEmerge = cell ? emergenceScore(cell) : 0;

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
                    <span className="truncate">{cell.name ?? cell.police_station ?? "This location"}</span>
                  </SheetTitle>
                  {(cell.police_station || roadLabel) && (
                    <div className="mt-0.5 pl-6 text-[12px] text-muted-foreground">
                      {[cell.name ? cell.police_station : null, roadLabel].filter(Boolean).join(" · ")}
                    </div>
                  )}
                </div>
                <span
                  className="flex shrink-0 items-center rounded-full px-2.5 py-1 text-xs font-semibold text-white"
                  style={{ background: prio.color }}
                >
                  {prio.word}
                </span>
              </div>
              <div className="flex flex-wrap items-center gap-2 pt-1">
                <a href={mapsUrl(cell.lat, cell.lon)} target="_blank" rel="noreferrer">
                  <Button size="sm" className="gap-1.5">
                    <Navigation className="h-3.5 w-3.5" /> Open in Maps
                  </Button>
                </a>
                {live?.deployed && (
                  <span className="flex items-center gap-1 rounded-full bg-amber-500/15 px-2 py-0.5 text-[11px] font-semibold text-amber-600">
                    <ShieldCheck className="h-3 w-3" /> Team here now
                  </span>
                )}
              </div>
            </SheetHeader>

            <div className="flex-1 space-y-5 overflow-y-auto p-5">
              {/* Plain one-liner: what is this place */}
              <p className="text-[14px] leading-snug">
                A <b>{prio.word.toLowerCase()}</b> spot for parking that blocks traffic.{" "}
                {blind && <span className="text-amber-600">It gets busy in the evening but is rarely checked then.</span>}
              </p>

              {/* KPI info cards — the same four numbers for every role */}
              <div className="grid grid-cols-4 gap-2">
                <InfoCard value={kPriority} label="Priority" hint="overall" tone="primary" />
                <InfoCard value={kPressure} label="Pressure" hint="how blocked" />
                <InfoCard value={kRepeat} label="Repeats" hint="how often" />
                <InfoCard value={kEmerge} label="Trend" hint="getting worse?" tone={kEmerge >= 60 ? "warning" : "default"} />
              </div>

              {/* HOW OFTEN — the heart of it */}
              <section className="space-y-2">
                <SectionTitle icon={<Repeat className="h-3.5 w-3.5" />}>How often it happens</SectionTitle>
                {hist ? (
                  <p className="text-[13px] leading-snug">
                    Ticketed <b>{num(hist.n_tickets, 0)}</b> times here so far.{" "}
                    {repeatPct != null && (
                      <>
                        About <b>{repeatPct}%</b> were the same vehicles coming back —{" "}
                        {habitual ? "so this is a regular, repeating problem." : "so it's mostly different people each time."}
                      </>
                    )}
                  </p>
                ) : loading ? (
                  <p className="text-[13px] text-muted-foreground">Loading…</p>
                ) : (
                  <p className="text-[13px] text-muted-foreground">Not much history here yet.</p>
                )}
                {live && (live.recent_30d > 0 || live.open > 0 || live.closed > 0) && (
                  <div className="flex flex-wrap gap-1.5">
                    {live.recent_30d > 0 && <Badge variant="secondary">{live.recent_30d} new this month</Badge>}
                    {live.open > 0 && <Badge variant="warning">{live.open} still open</Badge>}
                    {live.closed > 0 && <Badge variant="secondary">{live.closed} fixed</Badge>}
                  </div>
                )}
              </section>

              {/* WHEN — busiest times */}
              {hist && (
                <section className="space-y-1.5">
                  <SectionTitle icon={<Clock className="h-3.5 w-3.5" />}>When it's busiest</SectionTitle>
                  <HourBars values={hist.hourly_histogram} />
                  <p className="text-[11px] leading-snug text-muted-foreground">
                    Orange = the 5–9 PM evening rush. Based on when tickets were given.
                  </p>
                </section>
              )}

              {/* WHAT — main problems */}
              {hist && hist.violation_mix.length > 0 && (
                <section className="space-y-1.5">
                  <SectionTitle icon={<Ban className="h-3.5 w-3.5" />}>Main problems here</SectionTitle>
                  <MixBars items={hist.violation_mix.slice(0, 4)} />
                </section>
              )}

              {/* WHO — vehicles */}
              {hist && hist.vehicle_mix.length > 0 && (
                <section className="space-y-1.5">
                  <SectionTitle icon={<Car className="h-3.5 w-3.5" />}>Vehicles involved</SectionTitle>
                  <MixBars items={hist.vehicle_mix.slice(0, 4)} />
                </section>
              )}

              {/* WHAT CAN BE DONE */}
              <section className="rounded-xl border border-primary/30 bg-primary/5 p-3">
                <div className="flex items-start gap-2">
                  <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                  <div>
                    <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">What can be done here</div>
                    <div className="mt-0.5 text-sm font-semibold">
                      {monitorOnly ? "Keep an eye on it" : rec.action}
                      {blind && " + an evening sweep"}
                    </div>
                    {!monitorOnly && rec.window !== "—" && <div className="mt-0.5 text-[12px] text-muted-foreground">{rec.window}</div>}
                  </div>
                </div>
              </section>
            </div>

            {children && <div className="border-t p-4">{children}</div>}
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
