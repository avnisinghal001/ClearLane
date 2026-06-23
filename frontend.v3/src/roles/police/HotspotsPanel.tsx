import { useMemo } from "react";
import { MapPin, Route as RouteIcon, TrendingUp } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { BarSpark } from "@/components/Sparkline";
import { DOW } from "@/lib/time";
import { cellLabel } from "@/lib/signals";
import type { Cell, DispatchRoute } from "@/lib/types";

export function HotspotsPanel({
  cells,
  route,
  onFocus,
}: {
  cells: Cell[];
  route: DispatchRoute | null;
  onFocus: (c: Cell) => void;
}) {
  // Next-day priority zones: rank this station's cells by forecast weekly load,
  // falling back to PIC where no forecast exists.
  const ranked = useMemo(
    () =>
      [...cells]
        .sort((a, b) => (b.weekly_expected ?? b.pic_score) - (a.weekly_expected ?? a.pic_score))
        .slice(0, 12),
    [cells],
  );
  const stopSet = useMemo(() => new Set(route?.stops.map((s) => s.h3_r10) ?? []), [route]);

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card className="lg:col-span-1">
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-base">
            <RouteIcon className="h-4 w-4 text-primary" /> Recommended route
          </CardTitle>
        </CardHeader>
        <CardContent>
          {route && route.stops.length ? (
            <>
              <div className="mb-2 flex items-center gap-2 text-sm text-muted-foreground">
                <Badge variant="secondary">{route.n_stops} stops</Badge>
                <span>{route.route_km} km</span>
              </div>
              <ol className="space-y-1.5">
                {route.stops.map((s, i) => (
                  <li key={s.h3_r10} className="flex items-center gap-2 text-sm">
                    <span className="flex h-5 w-5 items-center justify-center rounded-full bg-primary text-[11px] font-bold text-primary-foreground">
                      {i + 1}
                    </span>
                    <span className="truncate text-xs font-medium">{cellLabel(s)}</span>
                    <span className="ml-auto shrink-0 font-semibold">Pressure {Math.round(s.pic_score)}</span>
                  </li>
                ))}
              </ol>
              <p className="mt-3 text-[11px] leading-tight text-muted-foreground">
                Optimised patrol route. Area-level only — never per officer.
              </p>
            </>
          ) : (
            <p className="text-sm text-muted-foreground">No optimiser route for this station in the current plan.</p>
          )}
        </CardContent>
      </Card>

      <Card className="lg:col-span-2">
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-base">
            <TrendingUp className="h-4 w-4 text-primary" /> Next-day priority zones
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {ranked.length === 0 && <p className="text-sm text-muted-foreground">No cells in this jurisdiction.</p>}
          {ranked.map((c, i) => (
            <div key={c.h3_r10} className="flex items-center gap-3 rounded-lg border p-2.5">
              <span className="num w-5 text-center text-sm font-bold text-muted-foreground">{i + 1}</span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate text-sm font-medium">{cellLabel(c)}</span>
                  {stopSet.has(c.h3_r10) && <Badge variant="default">on route</Badge>}
                  {c.emerging && <Badge variant="warning">rising</Badge>}
                </div>
                <div className="mt-0.5 text-xs text-muted-foreground">
                  Pressure {Math.round(c.pic_score)}
                </div>
              </div>
              {c.dow_curve && <BarSpark values={c.dow_curve} labels={DOW} height={34} className="w-28" />}
              <Button size="icon" variant="ghost" onClick={() => onFocus(c)} title="Show on map">
                <MapPin className="h-4 w-4" />
              </Button>
            </div>
          ))}
          <p className="pt-1 text-[11px] leading-tight text-muted-foreground">
            Ranked by expected next-day parking pressure (recorded weekday pattern). A forecast — not measured congestion.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
