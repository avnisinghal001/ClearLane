import { useCallback, useEffect, useMemo, useState } from "react";
import { CircleMarker, MapContainer, Marker, Polyline, Popup, Tooltip, useMap, useMapEvents } from "react-leaflet";
import L from "leaflet";
import { Layers, Crosshair, Flame, Car, Route as RouteIcon } from "lucide-react";
import type { Cell, DispatchRoute } from "@/lib/types";
import { cn } from "@/lib/utils";
import { sourceMeta } from "@/lib/format";
import { BaseLayer, type BaseKind } from "./BaseLayer";
import { TrafficLayer } from "./TrafficLayer";
import { HeatLayer } from "./HeatLayer";
import { circleColor, circleRadius, displayIntensity, heatPoints, type ColorMode } from "./layers";
import { numIcon, pinIcon, userIcon } from "./pin";

const BLR: [number, number] = [12.9716, 77.5946];

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
  mapKey: string | null;
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

function Camera({ flyTo, user, defaultZoom }: { flyTo?: [number, number] | null; user?: [number, number] | null; defaultZoom: number }) {
  const map = useMap();
  // Center on the user's location once on load.
  useEffect(() => {
    if (user) map.setView(user, Math.max(map.getZoom(), 14), { animate: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.[0], user?.[1]]);
  useEffect(() => {
    if (flyTo) map.flyTo(flyTo, Math.max(map.getZoom(), 16), { duration: 0.8 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flyTo?.[0], flyTo?.[1]]);
  // keep tiles sized correctly after layout shifts
  useEffect(() => {
    const t = setTimeout(() => map.invalidateSize(), 250);
    return () => clearTimeout(t);
  }, [map, defaultZoom]);
  return null;
}

function MapRef({ onReady }: { onReady: (m: L.Map) => void }) {
  const map = useMap();
  useEffect(() => onReady(map), [map, onReady]);
  return null;
}

function PickHandler({ active, onPick }: { active: boolean; onPick?: (ll: [number, number]) => void }) {
  useMapEvents({
    click(e) {
      if (active && onPick) onPick([e.latlng.lat, e.latlng.lng]);
    },
  });
  return null;
}

const ROUTE_COLORS = ["#ea580c", "#2563eb", "#16a34a", "#9333ea", "#dc2626", "#0891b2"];

export function ClearLaneMap({
  cells,
  source,
  mapKey,
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
  const [base, setBase] = useState<BaseKind>("mappls");
  const [baseResolved, setBaseResolved] = useState<"mappls" | "carto" | null>(null);
  const [showHeat, setShowHeat] = useState(defaultHeat);
  const [trafficOn, setTrafficOn] = useState(false);
  const [trafficStatus, setTrafficStatus] = useState<"on" | "unavailable" | null>(null);
  const [colorMode, setColorMode] = useState<ColorMode>("pic");
  const [showRoutes, setShowRoutes] = useState(Boolean(routes?.length));
  const [open, setOpen] = useState(false);
  const [mapInst, setMapInst] = useState<L.Map | null>(null);

  const onResolved = useCallback((w: "mappls" | "carto") => setBaseResolved(w), []);
  const onTraffic = useCallback((s: "on" | "unavailable") => setTrafficStatus(s), []);

  const maxIntensity = useMemo(() => Math.max(1, ...cells.map((c) => displayIntensity(c, source))), [cells, source]);
  const heat = useMemo(() => heatPoints(cells, source), [cells, source]);

  return (
    <div className={cn("relative h-full w-full overflow-hidden", className)}>
      <MapContainer center={BLR} zoom={defaultZoom} preferCanvas zoomControl={false} className="h-full w-full">
        <BaseLayer base={base} mapKey={mapKey} onResolved={onResolved} />
        {trafficOn && <TrafficLayer mapKey={mapKey} onStatus={onTraffic} />}
        <MapRef onReady={setMapInst} />
        <Camera flyTo={flyTo} user={userLocation} defaultZoom={defaultZoom} />
        <PickHandler active={pickMode} onPick={onPick} />

        {showHeat && heat.length > 0 && <HeatLayer points={heat} />}

        {!showHeat &&
          cells.map((c) => {
            const r = circleRadius(c, source, maxIntensity);
            const col = circleColor(c, colorMode);
            return (
              <CircleMarker
                key={c.h3_r10}
                center={[c.lat, c.lon]}
                radius={r}
                pathOptions={{
                  color: c.emerging ? "#b91c1c" : col,
                  weight: c.emerging ? 2 : 0.6,
                  fillColor: col,
                  fillOpacity: 0.62,
                }}
                eventHandlers={{ click: () => onCellClick?.(c) }}
              >
                <Tooltip direction="top" offset={[0, -2]} opacity={1}>
                  <span className="text-[11px] font-medium">
                    {c.police_station || "—"} · PIC {Math.round(c.pic_score)}
                    {c.emerging ? " · emerging" : ""}
                  </span>
                </Tooltip>
              </CircleMarker>
            );
          })}

        {/* numbered dispatch route overlay */}
        {showRoutes &&
          routes?.map((rt, ri) =>
            rt.stops.length ? (
              <Polyline
                key={"line-" + rt.station}
                positions={rt.stops.map((s) => [s.lat, s.lon] as [number, number])}
                pathOptions={{ color: ROUTE_COLORS[ri % ROUTE_COLORS.length], weight: 3, opacity: 0.8, dashArray: "6 4" }}
              />
            ) : null,
          )}
        {showRoutes &&
          routes?.flatMap((rt, ri) =>
            rt.stops.map((s, si) => (
              <Marker key={`stop-${rt.station}-${si}`} position={[s.lat, s.lon]} icon={numIcon(si + 1, ROUTE_COLORS[ri % ROUTE_COLORS.length])}>
                <Popup>
                  <b>{rt.station}</b> — stop {si + 1}
                  <br />
                  PIC {Math.round(s.pic_score)} · {s.h3_r10}
                </Popup>
              </Marker>
            )),
          )}

        {/* role pins (problem cells, open complaints, etc.) */}
        {pins?.map((p) => (
          <Marker key={p.key} position={[p.lat, p.lon]} icon={pinIcon(p.color || "#ea580c", p.pulse)} eventHandlers={{ click: () => p.onClick?.() }}>
            {p.label && <Popup>{p.label}</Popup>}
          </Marker>
        ))}

        {userLocation && (
          <Marker position={userLocation} icon={userIcon()} zIndexOffset={1000}>
            <Tooltip direction="top">You are here</Tooltip>
          </Marker>
        )}
      </MapContainer>

      {/* layer controls */}
      <div className="absolute right-3 top-3 z-[500] flex flex-col items-end gap-2">
        <button
          onClick={() => setOpen((o) => !o)}
          className="flex h-10 w-10 items-center justify-center rounded-full border bg-background/95 text-foreground shadow-md backdrop-blur hover:bg-accent"
          aria-label="Map layers"
        >
          <Layers className="h-5 w-5" />
        </button>
        {open && (
          <div className="w-60 animate-slide-up rounded-xl border bg-background/97 p-3 text-sm shadow-xl backdrop-blur">
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Layers</div>
            <Toggle icon={<Flame className="h-4 w-4" />} label="Heatmap" checked={showHeat} onChange={setShowHeat} />
            <div className="my-1">
              <label className="flex cursor-pointer items-center justify-between gap-2 rounded-md px-1 py-1.5 hover:bg-accent">
                <span className="flex items-center gap-2">
                  <Car className="h-4 w-4" /> Live traffic
                </span>
                <input type="checkbox" checked={trafficOn} onChange={(e) => setTrafficOn(e.target.checked)} className="accent-primary" />
              </label>
              {trafficOn && trafficStatus === "unavailable" && (
                <div className="px-1 pb-1 text-[11px] leading-tight text-muted-foreground">
                  Live Mappls traffic unavailable here (key/quota). Not simulated from tickets.
                </div>
              )}
            </div>
            {Boolean(routes?.length) && (
              <Toggle icon={<RouteIcon className="h-4 w-4" />} label="Dispatch route" checked={showRoutes} onChange={setShowRoutes} />
            )}
            <div className="mt-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Color points by</div>
            <select
              value={colorMode}
              onChange={(e) => setColorMode(e.target.value as ColorMode)}
              className="mt-1 w-full rounded-md border bg-background px-2 py-1.5 text-sm"
            >
              <option value="pic">PIC score</option>
              <option value="operational">Operational priority</option>
              <option value="source">Congestion source</option>
            </select>
            <div className="mt-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Base map</div>
            <select
              value={base}
              onChange={(e) => setBase(e.target.value as BaseKind)}
              className="mt-1 w-full rounded-md border bg-background px-2 py-1.5 text-sm"
            >
              <option value="mappls">Mappls{baseResolved === "carto" ? " (→ Carto fallback)" : ""}</option>
              <option value="light">Carto Light</option>
              <option value="osm">OpenStreetMap</option>
            </select>
          </div>
        )}
      </div>

      {/* recenter on user */}
      {userLocation && (
        <button
          onClick={() => mapInst?.flyTo(userLocation, Math.max(mapInst.getZoom(), 15), { duration: 0.7 })}
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
            <div className="mb-1 font-medium">{colorMode === "operational" ? "Operational priority" : source === "forecast" ? "Forecast intensity" : "PIC score"}</div>
            <div className="h-2 w-32 rounded-full" style={{ background: "linear-gradient(90deg,#fde68a,#fb923c,#ea580c,#b91c1c)" }} />
            <div className="mt-0.5 flex justify-between text-muted-foreground">
              <span>low</span>
              <span>high</span>
            </div>
            <div className="mt-0.5 text-muted-foreground">modeled from tickets · not measured congestion</div>
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
