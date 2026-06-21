import { useEffect, useState } from "react";
import { Wifi, WifiOff } from "lucide-react";
import { isLive, onLiveChange } from "@/lib/api";
import { cn } from "@/lib/utils";

export function LiveBadge({ className }: { className?: string }) {
  const [live, setLive] = useState(isLive());
  useEffect(() => onLiveChange(setLive), []);
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold",
        live ? "bg-[hsl(var(--success))]/12 text-[hsl(var(--success))]" : "bg-muted text-muted-foreground",
        className,
      )}
      title={live ? "Connected to the live backend" : "Backend unreachable — running on the bundled demo data"}
    >
      {live ? <Wifi className="h-3.5 w-3.5" /> : <WifiOff className="h-3.5 w-3.5" />}
      {live ? "LIVE" : "DEMO"}
    </span>
  );
}
