import type { ReactNode } from "react";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export function Kpi({
  label,
  value,
  sub,
  icon,
  tone = "default",
  className,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  icon?: ReactNode;
  tone?: "default" | "primary" | "success" | "warning";
  className?: string;
}) {
  const toneRing = {
    default: "",
    primary: "ring-1 ring-primary/20",
    success: "ring-1 ring-[hsl(var(--success))]/25",
    warning: "ring-1 ring-[hsl(var(--warning))]/30",
  }[tone];
  const iconBg = {
    default: "bg-muted text-muted-foreground",
    primary: "bg-accent text-accent-foreground",
    success: "bg-[hsl(var(--success))]/12 text-[hsl(var(--success))]",
    warning: "bg-[hsl(var(--warning))]/12 text-[hsl(var(--warning))]",
  }[tone];
  return (
    <Card className={cn("p-4", toneRing, className)}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</div>
          <div className="num mt-1 text-2xl font-bold leading-none">{value}</div>
          {sub && <div className="mt-1.5 text-xs text-muted-foreground">{sub}</div>}
        </div>
        {icon && <div className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-lg", iconBg)}>{icon}</div>}
      </div>
    </Card>
  );
}
