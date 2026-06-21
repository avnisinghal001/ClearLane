import { Clock, CalendarDays, CalendarClock } from "lucide-react";
import type { When } from "@/lib/types";
import { cn } from "@/lib/utils";
import { dowLabel, fmtHour, isAssumedPeak } from "@/lib/time";

export interface TimeValue {
  when: When;
  hour: number;
}

const OPTIONS: { key: When; label: string; icon: typeof Clock }[] = [
  { key: "now", label: "Now", icon: Clock },
  { key: "today", label: "Today", icon: CalendarDays },
  { key: "tomorrow", label: "Tomorrow", icon: CalendarClock },
];

export function TimeControl({
  value,
  onChange,
  className,
}: {
  value: TimeValue;
  onChange: (v: TimeValue) => void;
  className?: string;
}) {
  const isForecast = value.when !== "now";
  const peak = isAssumedPeak(value.hour);
  return (
    <div className={cn("rounded-xl border bg-background/95 p-2 shadow-sm backdrop-blur", className)}>
      <div className="grid grid-cols-3 gap-1 rounded-lg bg-muted p-1">
        {OPTIONS.map((o) => {
          const active = value.when === o.key;
          const Icon = o.icon;
          return (
            <button
              key={o.key}
              onClick={() => onChange({ ...value, when: o.key })}
              className={cn(
                "flex items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-sm font-medium transition-colors",
                active ? "bg-background text-foreground shadow" : "text-muted-foreground hover:text-foreground",
              )}
            >
              <Icon className="h-4 w-4" />
              {o.label}
            </button>
          );
        })}
      </div>

      {isForecast ? (
        <div className="px-1 pt-2">
          <div className="flex items-baseline justify-between">
            <span className="text-xs font-medium text-muted-foreground">
              {dowLabel(value.when)} · forecast
            </span>
            <span className={cn("num text-sm font-semibold", peak ? "text-primary" : "text-foreground")}>
              {fmtHour(value.hour)}
              {peak ? ` · assumed ${peak} window` : ""}
            </span>
          </div>
          <input
            type="range"
            min={0}
            max={23}
            value={value.hour}
            onChange={(e) => onChange({ ...value, hour: +e.target.value })}
            className="mt-1.5 w-full accent-primary"
          />
          <p className="mt-1 text-[11px] leading-tight text-muted-foreground">
            Modeled expected violations (recorded weekday × hour-of-day pattern). Congestion windows are stated
            assumptions — <b>not</b> measured peaks.
          </p>
        </div>
      ) : (
        <p className="px-1 pt-2 text-[11px] leading-tight text-muted-foreground">
          Live snapshot — PIC blends bias-corrected intensity with congestion severity (provenance badged per cell).
        </p>
      )}
    </div>
  );
}
