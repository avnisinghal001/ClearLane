import { useState } from "react";
import { Clock, CalendarClock, CalendarRange, Sparkles, History, ChevronDown, ChevronLeft, ChevronRight } from "lucide-react";
import type { When } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Switch } from "@/components/ui/switch";
import { fmtHour, isAssumedPeak } from "@/lib/time";

export interface TimeValue {
  when: When;
  hour: number;
  date?: string; // YYYY-MM-DD, used when when === "custom"
}

// Three clear lenses: live now, tomorrow's forecast, or ANY specific day.
const OPTIONS: { key: When; label: string; icon: typeof Clock }[] = [
  { key: "now", label: "Now", icon: Clock },
  { key: "tomorrow", label: "Tomorrow", icon: CalendarClock },
  { key: "custom", label: "Pick a day", icon: CalendarRange },
];

const todayStr = () => new Date().toISOString().slice(0, 10);

// Current Bengaluru (IST = UTC+5:30) hour 0..23 — what "Now" should snap to.
function istHourNow(): number {
  return Math.floor((Date.now() / 3_600_000 + 5.5) % 24);
}

function addDays(dateStr: string, n: number): string {
  const d = new Date((dateStr || todayStr()) + "T00:00:00");
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
}

function dayHeading(when: When, date?: string): string {
  if (when === "now") return "Now · today";
  if (when === "tomorrow") return "Tomorrow";
  const d = new Date((date || todayStr()) + "T00:00:00");
  return d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
}

/**
 * Unified, responsive time lens. Now / Tomorrow / Pick-a-day + a 24h scrubber.
 * `allDay` (government only) flips to hour-independent priority sizing. Drives
 * /api/v3/map?when=&hour=&date=. Modeled, never measured.
 */
export function TimeControl({
  value,
  onChange,
  allDay,
  onAllDayChange,
  plain,
  className,
}: {
  value: TimeValue;
  onChange: (v: TimeValue) => void;
  allDay?: boolean;
  onAllDayChange?: (v: boolean) => void;
  plain?: boolean; // citizen-friendly copy (no ML jargon), keeps the honesty essence
  className?: string;
}) {
  const peak = isAssumedPeak(value.hour);
  const isCustom = value.when === "custom";
  const isLearning = value.when !== "custom";
  const showAllDay = typeof onAllDayChange === "function";
  const hideHour = showAllDay && allDay;
  const [open, setOpen] = useState(
    () => !(typeof window !== "undefined" && window.matchMedia?.("(max-width: 767px)").matches),
  );

  function pick(key: When) {
    onChange({
      ...value,
      when: key,
      hour: key === "now" ? istHourNow() : value.hour,
      date: key === "custom" ? value.date || todayStr() : value.date,
    });
  }

  return (
    <div className={cn("rounded-xl border bg-background/95 p-2 shadow-sm backdrop-blur", className)}>
      {/* accordion header — collapse to free the map (esp. mobile) */}
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between gap-2 rounded-md px-1 py-0.5 text-left"
        aria-expanded={open}
        aria-label="Toggle time lens"
      >
        <span className="flex min-w-0 items-center gap-1.5 text-xs font-semibold">
          <Clock className="h-3.5 w-3.5 shrink-0 text-primary" /> Time lens
          <span className="num truncate font-normal text-muted-foreground">
            · {dayHeading(value.when, value.date)}{hideHour ? " · all-day" : ` · ${fmtHour(value.hour)}`}
          </span>
        </span>
        <ChevronDown className={cn("h-4 w-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")} />
      </button>

      {open && (
        <div className="mt-1.5 space-y-2">
          {/* mode selector — 3 equal segments, responsive */}
          <div className="grid grid-cols-3 gap-1 rounded-lg bg-muted p-1">
            {OPTIONS.map((o) => {
              const active = value.when === o.key;
              const Icon = o.icon;
              return (
                <button
                  key={o.key}
                  onClick={() => pick(o.key)}
                  aria-pressed={active}
                  className={cn(
                    "flex items-center justify-center gap-1.5 rounded-md px-1.5 py-1.5 text-[13px] font-medium transition-colors",
                    active ? "bg-background text-foreground shadow" : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  <Icon className="h-4 w-4 shrink-0" />
                  <span className="hidden sm:inline">{o.label}</span>
                </button>
              );
            })}
          </div>

          {/* day stepper + date picker (Pick-a-day) */}
          {isCustom && (
            <div className="flex items-center gap-1.5 px-1">
              <button
                onClick={() => onChange({ ...value, date: addDays(value.date || todayStr(), -1) })}
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border bg-background hover:bg-accent"
                aria-label="Previous day"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
              <input
                type="date"
                value={value.date || todayStr()}
                onChange={(e) => onChange({ ...value, date: e.target.value })}
                className="min-w-0 flex-1 rounded-md border bg-background px-2 py-1.5 text-sm"
                aria-label="Pick a date"
              />
              <button
                onClick={() => onChange({ ...value, date: addDays(value.date || todayStr(), 1) })}
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border bg-background hover:bg-accent"
                aria-label="Next day"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          )}

          {/* all-day toggle (government) */}
          {showAllDay && (
            <label className="flex cursor-pointer items-center justify-between gap-2 px-1 text-xs text-muted-foreground">
              <span>All-day priority (hour-independent)</span>
              <Switch checked={!!allDay} onCheckedChange={onAllDayChange} />
            </label>
          )}

          {/* hour scrubber */}
          {!hideHour && (
            <div className="px-1">
              <div className="flex items-baseline justify-between">
                <span className="text-xs font-medium text-muted-foreground">Hour of day</span>
                <span className={cn("num text-sm font-semibold", peak ? "text-primary" : "text-foreground")}>
                  {fmtHour(value.hour)}
                  {peak ? ` · ${peak} peak` : ""}
                </span>
              </div>
              <input
                type="range"
                min={0}
                max={23}
                value={value.hour}
                onChange={(e) => onChange({ ...value, hour: +e.target.value })}
                className="mt-1.5 w-full accent-primary"
                aria-label="Hour of day"
              />
            </div>
          )}

          {/* honest source label */}
          <div className="flex items-start gap-1.5 px-1">
            {isLearning ? (
              <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
            ) : (
              <History className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            )}
            <p className="text-[11px] leading-tight text-muted-foreground">
              {plain ? (
                <>
                  <b className="text-foreground">{isLearning ? (value.when === "now" ? "Right now" : "Forecast") : "Estimated day view"}</b>{" "}
                  — where parking problems are likely{value.when === "now" ? " right now" : ""}. Estimated, not live traffic.
                </>
              ) : (
                <>
                  {isLearning ? (
                    <>
                      <b className="text-foreground">{value.when === "now" ? "Live · learning-adjusted" : "Tomorrow · learning-adjusted"}</b>{" "}
                      — historical PIC bent by the self-learning loop
                      {hideHour ? "" : " × modeled typical congestion for the hour"}.
                    </>
                  ) : (
                    <>
                      <b className="text-foreground">Historical only</b> — day-of-week propensity for the chosen day
                      {hideHour ? "" : " × modeled congestion"}. A rough-idea view, no live learning.
                    </>
                  )}{" "}
                  Modeled, not measured.
                </>
              )}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
