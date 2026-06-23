import { cn } from "@/lib/utils";

const DAYS = ["M", "T", "W", "T", "F", "S", "S"];

// Weekday × hour "fingerprint" — a tiny 7×24 grid coloured by ticket count.
// Pure CSS grid, themed with the primary token. Recorded enforcement activity by
// day/hour (officer shifts), NOT live traffic.
export function Heatmap({ grid, className }: { grid: number[][]; className?: string }) {
  const max = Math.max(1, ...grid.flat());
  return (
    <div className={cn("space-y-0.5", className)}>
      {grid.map((row, d) => (
        <div key={d} className="flex items-center gap-1">
          <span className="w-2.5 shrink-0 text-[9px] leading-none text-muted-foreground">{DAYS[d]}</span>
          <div className="grid flex-1 gap-px" style={{ gridTemplateColumns: "repeat(24, minmax(0, 1fr))" }}>
            {row.map((v, h) => (
              <div
                key={h}
                className="aspect-square rounded-[1px]"
                title={`${DAYS[d]} ${String(h).padStart(2, "0")}:00 — ${v} ticket${v === 1 ? "" : "s"}`}
                style={{
                  background: v
                    ? `hsl(var(--primary) / ${(0.14 + 0.86 * (v / max)).toFixed(3)})`
                    : "hsl(var(--muted))",
                }}
              />
            ))}
          </div>
        </div>
      ))}
      <div className="flex justify-between pl-3.5 pt-0.5 text-[8px] text-muted-foreground">
        <span>12am</span>
        <span>6am</span>
        <span>12pm</span>
        <span>6pm</span>
        <span>11pm</span>
      </div>
    </div>
  );
}
