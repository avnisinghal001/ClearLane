import { Database, CalendarDays, CalendarClock, CalendarRange, Sparkles, History } from "lucide-react";
import type { When } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Switch } from "@/components/ui/switch";
import { dowLabel, fmtHour, isAssumedPeak } from "@/lib/time";
import type { TimeValue } from "@/components/TimeControl";

const OPTIONS: { key: When; label: string; icon: typeof Database }[] = [
  { key: "now", label: "All data", icon: Database },
  { key: "today", label: "Today", icon: CalendarDays },
  { key: "tomorrow", label: "Tomorrow", icon: CalendarClock },
  { key: "custom", label: "Pick date", icon: CalendarRange },
];

const todayStr = () => new Date().toISOString().slice(0, 10);

// Government date lens: All data (live, city-wide) · Today · Tomorrow · Pick-a-date,
// with a 24-hour scrubber and an All-day toggle. Drives /api/v3/map?when&hour; the
// All-day switch flips the map to all-day priority (PIC) sizing, hour-independent.
export function DateLens({
  value,
  onChange,
  allDay,
  onAllDayChange,
  className,
}: {
  value: TimeValue;
  onChange: (v: TimeValue) => void;
  allDay: boolean;
  onAllDayChange: (v: boolean) => void;
  className?: string;
}) {
  const peak = isAssumedPeak(value.hour);
  const isLearning = value.when !== "custom";
  const isCustom = value.when === "custom";

  return (
    <div className={cn("rounded-xl border bg-background/95 p-2 shadow-sm backdrop-blur", className)}>
      <div className="grid grid-cols-4 gap-1 rounded-lg bg-muted p-1">
        {OPTIONS.map((o) => {
          const active = value.when === o.key;
          const Icon = o.icon;
          return (
            <button
              key={o.key}
              onClick={() => onChange({ ...value, when: o.key, date: o.key === "custom" ? value.date || todayStr() : value.date })}
              className={cn(
                "flex items-center justify-center gap-1 rounded-md px-1 py-1.5 text-[12px] font-medium transition-colors",
                active ? "bg-background text-foreground shadow" : "text-muted-foreground hover:text-foreground",
              )}
            >
              <Icon className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">{o.label}</span>
            </button>
          );
        })}
      </div>

      {isCustom && (
        <div className="px-1 pt-2">
          <label className="text-xs font-medium text-muted-foreground">Date</label>
          <input
            type="date"
            aria-label="Pick a date"
            value={value.date || todayStr()}
            onChange={(e) => onChange({ ...value, date: e.target.value })}
            className="mt-1 w-full rounded-md border bg-background px-2 py-1.5 text-sm"
          />
        </div>
      )}

      <div className="px-1 pt-2">
        <div className="flex items-center justify-between">
          <span className="text-xs font-medium text-muted-foreground">{allDay ? "All-day priority" : "Hour of day"}</span>
          <label className="flex cursor-pointer items-center gap-1.5 text-xs text-muted-foreground">
            All-day
            <Switch checked={allDay} onCheckedChange={onAllDayChange} />
          </label>
        </div>
        {!allDay && (
          <>
            <div className="mt-0.5 flex items-baseline justify-between">
              <span className="text-[11px] text-muted-foreground">scrub the modeled commute</span>
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
          </>
        )}
      </div>

      <div className="mt-1.5 flex items-start gap-1.5 px-1">
        {isLearning ? <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" /> : <History className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />}
        <p className="text-[11px] leading-tight text-muted-foreground">
          {isLearning ? <b className="text-foreground">Learning-adjusted</b> : <b className="text-foreground">Historical only</b>}
          {value.when !== "now" && value.when !== "custom" ? ` · ${dowLabel(value.when)}` : ""} —{" "}
          {allDay ? "all-day priority (PIC), hour-independent" : "× modeled typical congestion for the hour"}. Modeled, not measured.
        </p>
      </div>
    </div>
  );
}
