import { useState } from "react";
import { Clock, CalendarDays, CalendarClock, CalendarRange, Sparkles, History, ChevronDown } from "lucide-react";
import type { When } from "@/lib/types";
import { cn } from "@/lib/utils";
import { dowLabel, fmtHour, isAssumedPeak } from "@/lib/time";

export interface TimeValue {
  when: When;
  hour: number;
  date?: string; // YYYY-MM-DD, used when when === "custom"
}

const OPTIONS: { key: When; label: string; icon: typeof Clock }[] = [
  { key: "now", label: "Now", icon: Clock },
  { key: "today", label: "Today", icon: CalendarDays },
  { key: "tomorrow", label: "Tomorrow", icon: CalendarClock },
  { key: "custom", label: "Pick date", icon: CalendarRange },
];

function todayStr() {
  return new Date().toISOString().slice(0, 10);
}

export function TimeControl({
  value,
  onChange,
  className,
}: {
  value: TimeValue;
  onChange: (v: TimeValue) => void;
  className?: string;
}) {
  const peak = isAssumedPeak(value.hour);
  const isLearning = value.when === "now" || value.when === "today" || value.when === "tomorrow";
  const isCustom = value.when === "custom";
  // Collapsible — default OPEN on desktop, COLLAPSED on mobile so the panel doesn't
  // eat the small map (read the viewport once on mount).
  const [open, setOpen] = useState(() => (typeof window !== "undefined" && window.matchMedia?.("(max-width: 767px)").matches ? false : true));
  const whenLabel = OPTIONS.find((o) => o.key === value.when)?.label ?? "Now";

  return (
    <div className={cn("rounded-xl border bg-background/95 p-2 shadow-sm backdrop-blur", className)}>
      {/* accordion header — collapse the time panel to free the map (esp. mobile) */}
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between gap-2 rounded-md px-1 py-0.5 text-left"
        aria-expanded={open}
        aria-label="Toggle time controls"
      >
        <span className="flex items-center gap-1.5 text-xs font-semibold">
          <Clock className="h-3.5 w-3.5 text-primary" /> Time
          <span className="num font-normal text-muted-foreground">· {whenLabel} · {fmtHour(value.hour)}</span>
        </span>
        <ChevronDown className={cn("h-4 w-4 shrink-0 text-muted-foreground transition-transform", open ? "rotate-180" : "")} />
      </button>

      {!open ? null : (
      <div className="mt-1.5">
      <div className="grid grid-cols-4 gap-1 rounded-lg bg-muted p-1">
        {OPTIONS.map((o) => {
          const active = value.when === o.key;
          const Icon = o.icon;
          return (
            <button
              key={o.key}
              onClick={() => onChange({ ...value, when: o.key, date: o.key === "custom" ? value.date || todayStr() : value.date })}
              className={cn(
                "flex items-center justify-center gap-1 rounded-md px-1.5 py-1.5 text-[13px] font-medium transition-colors",
                active ? "bg-background text-foreground shadow" : "text-muted-foreground hover:text-foreground",
              )}
            >
              <Icon className="h-4 w-4" />
              <span className="hidden sm:inline">{o.label}</span>
            </button>
          );
        })}
      </div>

      {/* custom date picker */}
      {isCustom && (
        <div className="px-1 pt-2">
          <label className="text-xs font-medium text-muted-foreground">Date</label>
          <input
            type="date"
            value={value.date || todayStr()}
            onChange={(e) => onChange({ ...value, date: e.target.value })}
            className="mt-1 w-full rounded-md border bg-background px-2 py-1.5 text-sm"
          />
        </div>
      )}

      {/* hour scrubber — drives the 24 hourly heatmaps in every mode */}
      <div className="px-1 pt-2">
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

      {/* honest source label */}
      <div className="mt-1.5 flex items-start gap-1.5 px-1">
        {isLearning ? (
          <>
            <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" />
            <p className="text-[11px] leading-tight text-muted-foreground">
              <b className="text-foreground">Learning-adjusted</b>
              {value.when !== "now" ? ` · ${dowLabel(value.when)}` : ""} — historical PIC bent by the
              self-learning loop, × modeled typical congestion for the hour. Many zones expand/cool, not one.
            </p>
          </>
        ) : (
          <>
            <History className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            <p className="text-[11px] leading-tight text-muted-foreground">
              <b className="text-foreground">Historical only</b> — pure day-of-week propensity for the
              chosen date × modeled congestion. No learning, no live reports — a rough-idea view for other days.
            </p>
          </>
        )}
      </div>
      </div>
      )}
    </div>
  );
}
