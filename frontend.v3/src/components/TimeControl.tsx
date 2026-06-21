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

      {/* Hour scrubber — drives the 24 hourly heatmaps in EVERY mode (live + forecast) */}
      <div className="px-1 pt-2">
        <div className="flex items-baseline justify-between">
          <span className="text-xs font-medium text-muted-foreground">
            {isForecast ? `${dowLabel(value.when)} · forecast` : "Live"} · hour-of-day
          </span>
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
        <p className="mt-1 text-[11px] leading-tight text-muted-foreground">
          Heatmap = historical PIC × <b>modeled typical congestion</b> for this hour
          {isForecast ? ` (${dowLabel(value.when)} day-of-week propensity)` : ""}. Congestion varies by
          hour; ticket counts are day-of-week (upload time) — <b>not</b> measured peaks.
        </p>
      </div>
    </div>
  );
}
