import { Badge } from "@/components/ui/badge";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { sourceMeta } from "@/lib/format";
import type { CongestionSource } from "@/lib/types";

export function SourceBadge({ source }: { source: CongestionSource | null | undefined }) {
  const m = sourceMeta(source);
  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span>
            <Badge variant={m.variant} className="cursor-help">
              {m.label}
            </Badge>
          </span>
        </TooltipTrigger>
        <TooltipContent>{m.help}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
