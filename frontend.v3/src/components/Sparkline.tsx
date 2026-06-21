import { cn } from "@/lib/utils";

// Tiny bar sparkline (e.g. the weekday forecast curve). Pure SVG, no deps.
export function BarSpark({
  values,
  labels,
  highlight,
  className,
  height = 40,
}: {
  values: (number | null)[];
  labels?: string[];
  highlight?: number;
  className?: string;
  height?: number;
}) {
  const vals = values.map((v) => (v == null || Number.isNaN(v) ? 0 : v));
  const max = Math.max(1, ...vals);
  return (
    <div className={cn("flex items-end gap-1", className)} style={{ height }}>
      {vals.map((v, i) => (
        <div key={i} className="flex flex-1 flex-col items-center justify-end gap-0.5">
          <div
            className={cn("w-full rounded-sm", i === highlight ? "bg-primary" : "bg-primary/35")}
            style={{ height: `${Math.max(3, (v / max) * (height - (labels ? 14 : 0)))}px` }}
            title={labels ? `${labels[i]}: ${v.toFixed(1)}` : String(v)}
          />
          {labels && <span className="text-[9px] leading-none text-muted-foreground">{labels[i]}</span>}
        </div>
      ))}
    </div>
  );
}
