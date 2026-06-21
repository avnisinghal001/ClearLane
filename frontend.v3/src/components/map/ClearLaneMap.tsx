import { useEffect, useMemo, useRef, useState } from "react";
import { Layers, Crosshair, Flame, Car, Route as RouteIcon, Loader2, AlertTriangle } from "lucide-react";
import type { Cell, DispatchRoute } from "@/lib/types";
import { cn } from "@/lib/utils";
import { sourceMeta } from "@/lib/format";
import { toast } from "@/components/toast";
import { useMapKeys } from "@/hooks/useConfig";
import { initBestMap, PROVIDER_TOTAL, type MapEngine } from "./engines";
import type { CircleSpec, HeatPoint, PinSpec, PolylineSpec } from "./engines/types";
import { circleColor, circleRadius, displayIntensity, heatPoints, type ColorMode } from "./layers";

const BLR: [number, number] = [12.9716, 77.5946];
const ROUTE_COLORS = ["#ea580c", "#2563eb", "#16a34a", "#9333ea", "#dc2626", "#0891b2"];

export interface MapPin {
  key: string;
  lat: number;
  lon: number;
  color?: string;
  label?: string;
  pulse?: boolean;
  onClick?: () => void;
}

interface Props {
  cells: Cell[];
  source: "live" | "forecast";
  userLocation?: [number, number] | null;
  flyTo?: [number, number] | null;
  onCellClick?: (c: Cell) => void;
  pickMode?: boolean;
  onPick?: (latlon: [number, number]) => void;
  routes?: DispatchRoute[];
  pins?: MapPin[];
  defaultHeat?: boolean;
  defaultZoom?: number;
  className?: string;
}

export function ClearLaneMap({
  cells,
  source,
  userLocation,
  flyTo,
  onCellClick,
  pickMode = false,
  onPick,
  routes,
  pins,
  defaultHeat = false,
  defaultZoom = 12,
  className,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const engineRef = useRef<MapEngine | null>(null);
  const { restKey, staticKey, ready } = useMapKeys();

  const [info, setInfo] = useState<{ label: string; priority: number; supportsTraffic: boolean } | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [showHeat, setShowHeat] = useState(defaultHeat);
  const [trafficOn, setTrafficOn] = useState(false);
  const [colorMode, setColorMode] = useState<ColorMode>("pic");
  const [showRoutes, setShowRoutes] = useState(Boolean(routes?.length));
  const [panelOpen, setPanelOpen] = useState(false);

  // keep latest callbacks/flags without re-subscribing the map click handler
  const pickRef = useRef(pickMode);
  pickRef.current = pickMode;
  const onPickRef = useRef(onPick);
  onPickRef.current = onPick;
  const onCellRef = useRef(onCellClick);
  onCellRef.current = onCellClick;
  const centeredRef = useRef(false);

  // ---- init the engine fallback chain once keys are resolved -------------
  useEffect(() => {
    if (!ready || !containerRef.current) return;
    let cancelled = false;
    setStatus("loading");
    initBestMap({ container: containerRef.current, center: BLR, zoom: defaultZoom, restKey, staticKey })
      .then(({ engine, attempts }) => {
        if (cancelled) {
          engine.destroy();
          return;
        }
        engineRef.current = engine;
        setInfo({ label: engine.label, priority: engine.priority, supportsTraffic: engine.supportsTraffic });
        setStatus("ready");
        engine.onMapClick((lat, lon) => {
          if (pickRef.current && onPickRef.current) onPickRef.current([lat, lon]);
        });
        setTimeout(() => engine.invalidate(), 120);
        const failed = attempts.find((a) => !a.ok);
        if (engine.priority === 1) {
          toast(`Map ready · ${engine.label} (source ${engine.priority}/${PROVIDER_TOTAL})`, { tone: "success" });
        } else {
          toast(`${failed?.label ?? "Primary map"} unavailable — using ${engine.label} (source ${engine.priority}/${PROVIDER_TOTAL})`, {
            tone: "warning",
          });
        }
      })
      .catch(() => !cancelled && setStatus("error"));
    return () => {
      cancelled = true;
      engineRef.current?.destroy();
      engineRef.current = null;
    };
  }, [ready, restKey, staticKey, defaultZoom]);

  // ---- circles + heat -----------------------------------------------------
  const maxIntensity = useMemo(() => Math.max(1, ...cells.map((c) => displayIntensity(c, source))), [cells, source]);
  useEffect(() => {
    const engine = engineRef.current;
    if (!engine || status !== "ready") return;
    const circleSpecs: CircleSpec[] = cells.map((c) => ({
      id: c.h3_r10,
      lat: c.lat,
      lon: c.lon,
      radius: circleRadius(c, source, maxIntensity),
      color: c.emerging ? "#b91c1c" : circleColor(c, colorMode),
      fillColor: circleColor(c, colorMode),
      weight: c.emerging ? 2 : 0.6,
      tooltip: `${c.police_station || "—"} · PIC ${Math.round(c.pic_score)}${c.emerging ? " · emerging" : ""}`,
      onClick: () => onCellRef.current?.(c),
    }));
    const heatSpecs: HeatPoint[] = heatPoints(cells, source).map(([lat, lon, intensity]) => ({ lat, lon, intensity }));
    engine.setCircles(showHeat ? [] : circleSpecs);
    engine.setHeat(heatSpecs, showHeat);
  }, [cells, source, colorMode, showHeat, maxIntensity, status]);

  // ---- pins (role pins + numbered route stops + user) + route polylines ---
  useEffect(() => {
    const engine = engineRef.current;
    if (!engine || status !== "ready") return;
    const pinSpecs: PinSpec[] = (pins ?? []).map((p) => ({
      id: p.key,
      lat: p.lat,
      lon: p.lon,
      color: p.color ?? "#ea580c",
      pulse: p.pulse,
      popup: p.label,
      onClick: p.onClick,
      kind: "pin",
    }));
    if (showRoutes && routes) {
      routes.forEach((rt, ri) =>
        rt.stops.forEach((s, si) =>
          pinSpecs.push({
            id: `stop-${rt.station}-${si}`,
            lat: s.lat,
            lon: s.lon,
            color: ROUTE_COLORS[ri % ROUTE_COLORS.length],
            kind: "num",
            num: si + 1,
            popup: `${rt.station} — stop ${si + 1} · PIC ${Math.round(s.pic_score)}`,
          }),
        ),
      );
    }
    if (userLocation) pinSpecs.push({ id: "user", lat: userLocation[0], lon: userLocation[1], color: "#2563eb", kind: "user", popup: "You are here" });
    engine.setPins(pinSpecs);

    const lines: PolylineSpec[] =
      showRoutes && routes
        ? routes.map((rt, ri) => ({ id: rt.station, points: rt.stops.map((s) => [s.lat, s.lon] as [number, number]), color: ROUTE_COLORS[ri % ROUTE_COLORS.length] }))
        : [];
    engine.setPolylines(lines);
  }, [pins, routes, showRoutes, userLocation, status]);

  // ---- camera: fly-to + one-time center on the user ----------------------
  useEffect(() => {
    const engine = engineRef.current;
    if (engine && status === "ready" && flyTo) engine.setView(flyTo, Math.max(engine.getZoom(), 16));
  }, [flyTo, status]);
  useEffect(() => {
    const engine = engineRef.current;
    if (engine && status === "ready" && userLocation && !centeredRef.current) {
      engine.setView(userLocation, Math.max(engine.getZoom(), 14));
      centeredRef.current = true;
    }
  }, [userLocation, status]);

  // ---- traffic ------------------------------------------------------------
  useEffect(() => {
    const engine = engineRef.current;
    if (engine && status === "ready" && engine.supportsTraffic) engine.setTraffic(trafficOn);
  }, [trafficOn, status]);

  // ---- keep sized on layout/viewport changes ------------------------------
  useEffect(() => {
    const onResize = () => engineRef.current?.invalidate();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const trafficAvailable = info?.supportsTraffic ?? false;

  return (
    <div className={cn("relative h-full w-full overflow-hidden bg-muted", className)}>
      <div ref={containerRef} className="h-full w-full" />

      {/* loading / error states — never a blank map */}
      {status === "loading" && (
        <div className="absolute inset-0 z-[450] flex flex-col items-center justify-center gap-3 bg-background/70 backdrop-blur-sm">
          <Loader2 className="h-7 w-7 animate-spin text-primary" />
          <div className="text-sm font-medium text-muted-foreground">Loading map…</div>
        </div>
      )}
      {status === "error" && (
        <div className="absolute inset-0 z-[450] flex flex-col items-center justify-center gap-2 p-6 text-center">
          <AlertTriangle className="h-7 w-7 text-destructive" />
          <div className="font-semibold">Map unavailable</div>
          <div className="max-w-xs text-sm text-muted-foreground">All map providers failed to load. Check your network / API key & quota.</div>
        </div>
      )}

      {/* layer controls */}
      <div className="absolute right-3 top-3 z-[500] flex flex-col items-end gap-2">
        <button
          onClick={() => setPanelOpen((o) => !o)}
          className="flex h-10 w-10 items-center justify-center rounded-full border bg-background/95 text-foreground shadow-md backdrop-blur hover:bg-accent"
          aria-label="Map layers"
        >
          <Layers className="h-5 w-5" />
        </button>
        {panelOpen && (
          <div className="w-60 animate-slide-up rounded-xl border bg-background/97 p-3 text-sm shadow-xl backdrop-blur">
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Layers</div>
            <Toggle icon={<Flame className="h-4 w-4" />} label="Hourly heatmap" checked={showHeat} onChange={setShowHeat} />
            {trafficAvailable ? (
              <Toggle icon={<Car className="h-4 w-4" />} label="Mappls traffic tiles" checked={trafficOn} onChange={setTrafficOn} />
            ) : (
              <div className="flex items-center justify-between gap-2 rounded-md px-1 py-1.5 text-muted-foreground">
                <span className="flex items-center gap-2">
                  <Car className="h-4 w-4" /> Mappls traffic tiles
                </span>
                <span className="rounded bg-muted px-1.5 py-0.5 text-[10px]">basemap only</span>
              </div>
            )}
            <p className="px-1 pt-0.5 text-[10px] leading-tight text-muted-foreground">
              Live-traffic feed isn't enabled on this Mappls account — the hourly heatmap above is the
              modeled typical-congestion view (use the hour slider).
            </p>
            {Boolean(routes?.length) && <Toggle icon={<RouteIcon className="h-4 w-4" />} label="Dispatch route" checked={showRoutes} onChange={setShowRoutes} />}
            <div className="mt-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Color points by</div>
            <select value={colorMode} onChange={(e) => setColorMode(e.target.value as ColorMode)} className="mt-1 w-full rounded-md border bg-background px-2 py-1.5 text-sm">
              <option value="pic">PIC score</option>
              <option value="operational">Operational priority</option>
              <option value="source">Congestion source</option>
            </select>
            {info && (
              <div className="mt-2 text-[11px] text-muted-foreground">
                Basemap: <b>{info.label}</b> (source {info.priority}/{PROVIDER_TOTAL})
              </div>
            )}
          </div>
        )}
      </div>

      {/* recenter on user */}
      {userLocation && status === "ready" && (
        <button
          onClick={() => engineRef.current?.setView(userLocation, Math.max(engineRef.current.getZoom(), 15))}
          className="absolute bottom-3 right-3 z-[500] flex h-10 w-10 items-center justify-center rounded-full border bg-background/95 text-primary shadow-md backdrop-blur hover:bg-accent"
          aria-label="Recenter on my location"
          title="Recenter on my location"
        >
          <Crosshair className="h-5 w-5" />
        </button>
      )}

      {/* legend */}
      <div className="pointer-events-none absolute bottom-3 left-3 z-[500] max-w-[60%] rounded-lg border bg-background/95 px-3 py-2 text-[11px] shadow-md backdrop-blur">
        {colorMode === "source" ? (
          <div className="flex flex-col gap-0.5">
            {(["live", "mappls_typical", "modeled"] as const).map((s) => (
              <span key={s} className="flex items-center gap-1.5">
                <i className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: { live: "#16a34a", mappls_typical: "#f59e0b", modeled: "#4f7fd6" }[s] }} />
                {sourceMeta(s).label}
              </span>
            ))}
          </div>
        ) : (
          <>
            <div className="mb-1 font-medium">{colorMode === "operational" ? "Operational priority" : source === "forecast" ? "Forecast intensity" : "Hourly intensity"}</div>
            <div className="h-2 w-32 rounded-full" style={{ background: "linear-gradient(90deg,#16a34a,#84cc16,#facc15,#f97316,#dc2626)" }} />
            <div className="mt-0.5 flex justify-between text-muted-foreground">
              <span>low</span>
              <span>med</span>
              <span>high</span>
            </div>
            <div className="mt-0.5 text-muted-foreground">historical PIC × typical congestion for the hour · not measured</div>
          </>
        )}
      </div>
    </div>
  );
}

function Toggle({ icon, label, checked, onChange }: { icon: React.ReactNode; label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex cursor-pointer items-center justify-between gap-2 rounded-md px-1 py-1.5 hover:bg-accent">
      <span className="flex items-center gap-2">
        {icon} {label}
      </span>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="accent-primary" />
    </label>
  );
}
