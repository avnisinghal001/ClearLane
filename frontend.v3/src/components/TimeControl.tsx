import { useState } from "react";
import { Clock, CalendarClock, Sparkles, ChevronDown } from "lucide-react";
import type { When } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Switch } from "@/components/ui/switch";
import { fmtHour, isAssumedPeak } from "@/lib/time";

export interface TimeValue {
  when: When;
  hour: number;
  date?: string; // retained for the /api contract; unused now (no custom day)
}

// Two clear lenses only: LIVE now (current time, automatic) or TOMORROW's
// forecast (pick the hour to check the timing).
const OPTIONS: { key: When; label: string; icon: typeof Clock }[] = [
  { key: "now", label: "Now", icon: Clock },
  { key: "tomorrow", label: "Tomorrow", icon: CalendarClock },
];

// Current hour 0..23 in the USER's own timezone — what "Now" snaps to.
function localHourNow(): number {
  return new Date().getHours();
}

/**
 * Simplified time lens. "Now" = the user's current time (no slider); "Tomorrow"
 * = forecast with an hour scrubber so timing can be checked. `allDay` (government
 * only) flips to hour-independent priority sizing. Drives /api/v3/map?when=&hour=.
 * Modeled, never measured.
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
  const isNow = value.when === "now";
  const showAllDay = typeof onAllDayChange === "function";
  // Hour scrubber only matters for the Tomorrow forecast (Now = current time).
  const showHour = !isNow && !(showAllDay && allDay);
  const [open, setOpen] = useState(
    () => !(typeof window !== "undefined" && window.matchMedia?.("(max-width: 767px)").matches),
  );

  function pick(key: When) {
    onChange({
      ...value,
      when: key,
      // Now -> snap to the user's current hour; Tomorrow -> keep the chosen hour.
      hour: key === "now" ? localHourNow() : value.hour,
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
            · {isNow ? `Now · ${fmtHour(value.hour)}` : `Tomorrow · ${fmtHour(value.hour)}`}
          </span>
        </span>
        <ChevronDown className={cn("h-4 w-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")} />
      </button>

      {open && (
        <div className="mt-1.5 space-y-2">
          {/* mode selector — 2 equal segments */}
          <div className="grid grid-cols-2 gap-1 rounded-lg bg-muted p-1">
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
                  <span>{o.label}</span>
                </button>
              );
            })}
          </div>

          {/* all-day toggle (government) */}
          {showAllDay && (
            <label className="flex cursor-pointer items-center justify-between gap-2 px-1 text-xs text-muted-foreground">
              <span>All-day priority (hour-independent)</span>
              <Switch checked={!!allDay} onCheckedChange={onAllDayChange} />
            </label>
          )}

          {/* hour scrubber — Tomorrow forecast only */}
          {showHour && (
            <div className="px-1">
              <div className="flex items-baseline justify-between">
                <span className="text-xs font-medium text-muted-foreground">Forecast hour</span>
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
                aria-label="Forecast hour of day"
              />
            </div>
          )}

          {/* honest source label */}
          <div className="flex items-start gap-1.5 px-1">
            <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
            <p className="text-[11px] leading-tight text-muted-foreground">
              {plain ? (
                <>
                  <b className="text-foreground">{isNow ? "Right now" : "Tomorrow's forecast"}</b> — where parking
                  problems are likely{isNow ? " at the moment" : " tomorrow"}. Estimated, not live traffic.
                </>
              ) : (
                <>
                  <b className="text-foreground">{isNow ? "Live · learning-adjusted" : "Tomorrow · forecast"}</b> —
                  historical PIC bent by the self-learning loop
                  {showHour ? " × modeled typical congestion for the hour" : ""}. Modeled, not measured.
                </>
              )}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
