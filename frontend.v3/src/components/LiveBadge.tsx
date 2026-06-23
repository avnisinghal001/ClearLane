import { useEffect, useState } from "react";
import { Wifi } from "lucide-react";
import { isLive, onLiveChange } from "@/lib/api";
import { cn } from "@/lib/utils";

// Minimal connection indicator: a single wifi glyph, green when connected and
// muted otherwise. No "LIVE"/"DEMO" wording anywhere in the app chrome.
export function LiveBadge({ className }: { className?: string }) {
  const [live, setLive] = useState(isLive());
  useEffect(() => onLiveChange(setLive), []);
  return (
    <span
      className={cn(
        "inline-flex h-7 w-7 items-center justify-center rounded-full transition-colors",
        live ? "text-[hsl(var(--success))]" : "text-muted-foreground/60",
        className,
      )}
      title={live ? "Connected" : "Reconnecting…"}
      aria-label={live ? "Connected" : "Reconnecting"}
    >
      <Wifi className="h-[18px] w-[18px]" />
    </span>
  );
}
