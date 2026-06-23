import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Layers, Crosshair, Loader2, AlertTriangle, Sparkles, History, Play, Pause, X, ChevronDown, Palette,
} from "lucide-react";
import type { Cell, DispatchRoute } from "@/lib/types";
import { cn } from "@/lib/utils";
import { picColor } from "@/lib/format";
import { cellLabel, cellTier, flowImpactTable, isBlindSpot, priorityLabel, priorityScore, tierColor, flowColor } from "@/lib/signals";
import { useIsMobile } from "@/hooks/useMediaQuery";
import { Switch } from "@/components/ui/switch";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { useMapKeys } from "@/hooks/useConfig";
import { initBestMap, PROVIDER_TOTAL, type MapEngine } from "./engines";
import type { CircleSpec, DotSpec, HeatPoint, PinSpec, PolylineSpec, RingSpec, TrafficLineSpec } from "./engines/types";
import { circleColor, heatPoints, type ColorMode } from "./layers";

const BLR: [number, number] = [12.9716, 77.5946];
const ROUTE_COLORS = ["#ea580c", "#2563eb", "#16a34a", "#9333ea", "#dc2626", "#0891b2"];
const DOW_LONG = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const V1_CIRCLE_VISIBLE_FLOOR = 18; // below this active score, the zone disappears
const V1_RADIUS_MIN = 4;
const V1_RADIUS_MAX = 23;

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
  // Focus a single place: zoom in + show the animated ripple ("waves out") + a
  // numbers peek. Clicking the ripple opens the detail modal (via onCellClick).
  focus?: { lat: number; lon: number; h3?: string } | null;
  modalOpen?: boolean; // when the detail modal is open, suppress the numbers peek
  onCellClick?: (c: Cell) => void; // a map dot was clicked -> set the focus ripple (a "peek")
  onFocusOpen?: (c: Cell) => void; // the focus ripple was clicked -> open the detail modal
  pickMode?: boolean;
  onPick?: (latlon: [number, number]) => void;
  onLongPress?: (latlon: [number, number]) => void; // long-press / right-click -> report here
  onPickModeChange?: (on: boolean) => void; // citizen "file complaint (click map)" toggle
  enableComplaint?: boolean; // show the complaint-on-click toggle (citizen)
  evidence?: [number, number][]; // recorded ticket/report points for the evidence layer
  routes?: DispatchRoute[];
  pins?: MapPin[];
  defaultHeat?: boolean;
  defaultColorMode?: ColorMode;
  defaultZoom?: number;
  sizeMode?: "intensity" | "pressure"; // "pressure" = all-day PIC (hour-independent)
  bottomSafe?: boolean; // lift bottom controls above a mobile bottom nav (citizen)
  className?: string;
  audience?: "citizen" | "ops"; // "citizen" = plain lens chip (no ML counts)
  lens?: { badge?: string; nEmerging?: number; nAdjusted?: number; learningAdjusted?: boolean };
  // Live-traffic layer (police): show the toggle in the Layers accordion, render the
  // severity-coloured road segments, and call back when the toggle/zone-count changes
  // so the owner can (re)fetch. Avni's Phase-3 congestion brought onto the main map.
  liveTrafficEnabled?: boolean;
  liveTrafficDefaultOn?: boolean; // start with the live layer ON (police default)
  liveTraffic?: { segments: TrafficLineSpec[]; loading?: boolean; live?: boolean; coveragePct?: number };
  liveTrafficActive?: boolean;
  // h3 -> severity colour: when the live layer is on, recolour these hotspot dots by
  // live congestion severity (Avni's dot technique) instead of their tier colour.
  liveSeverityByCell?: Record<string, string>;
  onLiveTraffic?: (on: boolean, zones: number) => void;
}

const COLOR_OPTIONS: { value: ColorMode; label: string }[] = [
  { value: "tier", label: "Priority tier (P1–P4)" },
  { value: "pic", label: "PIC · time score (hour × day)" },
  { value: "flow", label: "Flow impact (modeled proxy)" },
  { value: "operational", label: "Operational priority" },
  { value: "source", label: "Congestion source" },
];

export function ClearLaneMap({
  cells,
  source,
  userLocation,
  flyTo,
  focus,
  modalOpen = false,
  onCellClick,
  onFocusOpen,
  pickMode = false,
  onPick,
  onLongPress,
  onPickModeChange,
  enableComplaint = false,
  evidence,
  routes,
  pins,
  defaultHeat = false,
  defaultColorMode = "pic",
  defaultZoom = 12,
  sizeMode = "intensity",
  bottomSafe = false,
  className,
  audience = "ops",
  lens,
  liveTrafficEnabled = false,
  liveTrafficDefaultOn = false,
  liveTraffic,
  liveTrafficActive,
  liveSeverityByCell,
  onLiveTraffic,
}: Props) {
  const bottomCls = bottomSafe ? "bottom-[5.5rem] md:bottom-3" : "bottom-3";
  const containerRef = useRef<HTMLDivElement>(null);
  const engineRef = useRef<MapEngine | null>(null);
  const { restKey, staticKey, useMappls, ready } = useMapKeys();
  const isMobile = useIsMobile();

  const [info, setInfo] = useState<{ label: string; priority: number; supportsTraffic: boolean } | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [panelOpen, setPanelOpen] = useState(false);
  // floating panels are collapsible (accordion) — default OPEN on desktop, COLLAPSED
  // on mobile to free the small map (lazy initialiser reads the viewport once).
  const phoneInit = () => (typeof window !== "undefined" && window.matchMedia?.("(max-width: 767px)").matches ? false : true);
  const [legendOpen, setLegendOpen] = useState(phoneInit);
  const [captionOpen, setCaptionOpen] = useState(phoneInit);

  // view mode
  const [simple, setSimple] = useState(false);
  const [hourActivity, setHourActivity] = useState(false);
  // overlays
  const [showRings, setShowRings] = useState(true);
  const [showEvidence, setShowEvidence] = useState(false);
  const [replayOn, setReplayOn] = useState(false);
  const [replayIdx, setReplayIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(900);
  // appearance
  const [colorMode, setColorMode] = useState<ColorMode>(defaultColorMode);
  const [showHeat, setShowHeat] = useState(defaultHeat);
  const [trafficOn, setTrafficOn] = useState(false);
  const [showRoutes, setShowRoutes] = useState(Boolean(routes?.length));
  // live-traffic layer (police): toggle + police-controlled zone count (10..20)
  const [liveOn, setLiveOn] = useState(liveTrafficDefaultOn);
  const [liveZones, setLiveZones] = useState(15);
  const onLiveTrafficRef = useRef(onLiveTraffic);
  onLiveTrafficRef.current = onLiveTraffic;

  // keep latest callbacks/flags without re-subscribing the map click handler
  const pickRef = useRef(pickMode);
  pickRef.current = pickMode;
  const onPickRef = useRef(onPick);
  onPickRef.current = onPick;
  const onLongPressRef = useRef(onLongPress);
  onLongPressRef.current = onLongPress;
  const onCellRef = useRef(onCellClick);
  onCellRef.current = onCellClick;
  const onFocusOpenRef = useRef(onFocusOpen);
  onFocusOpenRef.current = onFocusOpen;
  const centeredRef = useRef(false);

  // flow-impact proxy table (for the "flow" color mode + ring tooltip), memoized
  const flowMap = useMemo(() => flowImpactTable(cells), [cells]);

  // ---- init the engine fallback chain once keys are resolved -------------
  useEffect(() => {
    if (!ready || !containerRef.current) return;
    let cancelled = false;
    setStatus("loading");
    initBestMap({ container: containerRef.current, center: BLR, zoom: defaultZoom, restKey, staticKey, disableMappls: !useMappls })
      .then(({ engine }) => {
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
        // long-press (mobile) / right-click (desktop) anywhere -> open a report here
        engine.onLongPress?.((lat, lon) => onLongPressRef.current?.([lat, lon]));
        setTimeout(() => engine.invalidate(), 120);
      })
      .catch(() => !cancelled && setStatus("error"));
    return () => {
      cancelled = true;
      engineRef.current?.destroy();
      engineRef.current = null;
    };
  }, [ready, restKey, staticKey, useMappls, defaultZoom]);

  // ---- replay animation timer (weekday cycle Mon→Sun) ---------------------
  useEffect(() => {
    if (!replayOn || !playing) return;
    const t = setInterval(() => setReplayIdx((i) => (i + 1) % 7), speed);
    return () => clearInterval(t);
  }, [replayOn, playing, speed]);

  // ---- display set (Simple view = P1/P2 only) -----------------------------
  const display = useMemo(() => (simple ? cells.filter((c) => { const t = cellTier(c); return t === "P1" || t === "P2"; }) : cells), [cells, simple]);

  const replayMax = useMemo(() => (replayOn ? Math.max(1, ...cells.map((c) => c.dow_curve?.[replayIdx] ?? 0)) : 1), [cells, replayOn, replayIdx]);
  const showLiveTrafficForLens = liveTrafficActive ?? source === "live";

  // ---- v1-style active visual score ---------------------------------------
  // One score drives BOTH visibility and colour/radius. Below the floor, a zone
  // disappears; above it, green→yellow→red and small→large are tied together.
  const activeVisualScore = useCallback(
    (c: Cell): number => {
      if (replayOn) return Math.max(0, Math.min(100, ((c.dow_curve?.[replayIdx] ?? 0) / replayMax) * 100));
      if (hourActivity) return Math.max(0, Math.min(100, (c.congestion_hour ?? 0) * 100));
      if (sizeMode === "pressure") return Math.max(0, Math.min(100, c.pressure ?? c.pic_score ?? 0));
      return Math.max(0, Math.min(100, c.activity_score ?? c.forecast_intensity ?? c.display_score ?? c.intensity ?? c.pic_score ?? 0));
    },
    [replayOn, replayIdx, replayMax, hourActivity, sizeMode],
  );

  const visibleDisplay = useMemo(
    () => display.filter((c) => activeVisualScore(c) >= V1_CIRCLE_VISIBLE_FLOOR || c.emerging || isBlindSpot(c)),
    [display, activeVisualScore],
  );

  const radiusOf = useCallback(
    (c: Cell): number => {
      const t = activeVisualScore(c) / 100;
      return V1_RADIUS_MIN + Math.sqrt(t) * (V1_RADIUS_MAX - V1_RADIUS_MIN);
    },
    [activeVisualScore],
  );

  // ---- circles + heat -----------------------------------------------------
  useEffect(() => {
    const engine = engineRef.current;
    if (!engine || status !== "ready") return;

    // When the live layer is on AND the owner says this lens is the real current
    // moment, monitored cells are coloured by LIVE severity. Scrubbing to another
    // hour/day lifts the override so dots follow the modeled time colour instead.
    const liveSev = (c: Cell): string | undefined =>
      liveOn && showLiveTrafficForLens ? liveSeverityByCell?.[c.h3_r10] : undefined;
    const fillOf = (c: Cell): string => liveSev(c) ?? (colorMode === "pic" ? picColor(activeVisualScore(c)) : replayOn ? picColor(activeVisualScore(c)) : circleColor(c, colorMode, flowMap));

    const circleSpecs: CircleSpec[] = visibleDisplay.map((c) => {
      const lift = c.learn_lift ?? 0;
      const expanding = lift >= 0.15;
      const blind = isBlindSpot(c);
      const onLive = Boolean(liveSev(c));
      const fill = fillOf(c);
      // live-monitored cells get a white casing + heavier weight so they read as the
      // live severity dots; otherwise the usual emerging/expanding/blind ring.
      const ring = onLive ? "#ffffff" : c.emerging ? "#b91c1c" : expanding ? "#f59e0b" : blind ? "#d97706" : fill;
      const liftTip = lift > 0.08 ? ` · ▲ expanding +${Math.round(lift * 100)}%` : lift < -0.08 ? ` · ▼ cooling ${Math.round(lift * 100)}%` : "";
      return {
        id: c.h3_r10,
        lat: c.lat,
        lon: c.lon,
        radius: radiusOf(c) + (onLive ? 3 : c.emerging ? 3 : expanding ? 1.5 : 0),
        color: ring,
        fillColor: fill,
        weight: onLive ? 2 : c.emerging ? 2.5 : expanding ? 1.6 : blind ? 1.4 : 0.6,
        tooltip: `${c.police_station || "—"} · ${cellTier(c)} · active ${Math.round(activeVisualScore(c))} · PIC ${Math.round(c.pic_score)}${onLive ? " · ● live congestion" : ""}${blind ? " · ◎ blind spot" : ""}${c.emerging ? " · ◆ emerging" : ""}${liftTip}`,
        onClick: () => onCellRef.current?.(c),
      };
    });
    const heatSpecs: HeatPoint[] = heatPoints(cells, source).map(([lat, lon, intensity]) => ({ lat, lon, intensity }));
    engine.setCircles(showHeat ? [] : circleSpecs);
    engine.setHeat(heatSpecs, showHeat);
    // TEMP render trace (dev-only) — confirms how many cells actually draw + which
    // engine won. Remove once the render path is verified in the field.
    if (import.meta.env.DEV)
      // eslint-disable-next-line no-console
      console.log(`[ClearLaneMap] engine=${engine.label} cells_in=${cells.length} display=${display.length} visible=${visibleDisplay.length} circles_drawn=${showHeat ? 0 : circleSpecs.length} heat_pts=${showHeat ? heatSpecs.length : 0} mode=${colorMode}`);
  }, [visibleDisplay, display.length, cells, colorMode, showHeat, status, replayOn, radiusOf, flowMap, liveOn, liveSeverityByCell, showLiveTrafficForLens, activeVisualScore]);

  // ---- evening blind-spot rings (dashed) ----------------------------------
  useEffect(() => {
    const engine = engineRef.current;
    if (!engine || status !== "ready") return;
    if (!showRings) {
      engine.setRings([]);
      return;
    }
    const rings: RingSpec[] = visibleDisplay
      .filter(isBlindSpot)
      .map((c) => ({
        id: `ring-${c.h3_r10}`,
        lat: c.lat,
        lon: c.lon,
        radius: radiusOf(c) + 6,
        color: "#d97706",
        weight: 1.4,
        dashArray: "4",
        tooltip: `${c.police_station || "—"} · evening blind spot (high-priority · under-observed)`,
      }));
    engine.setRings(rings);
  }, [visibleDisplay, showRings, status, radiusOf]);

  // ---- evidence points (recorded tickets/reports) -------------------------
  useEffect(() => {
    const engine = engineRef.current;
    if (!engine || status !== "ready") return;
    const dots: DotSpec[] = showEvidence && evidence ? evidence.map(([lat, lon], i) => ({ id: `ev-${i}`, lat, lon })) : [];
    engine.setDots(dots);
  }, [evidence, showEvidence, status]);

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

  // ---- focus ripple: zoom into ONE place, animate "waves out", show a small
  // numbers peek; clicking the ripple opens the detail modal. Driven by the URL
  // (?lat/lon/h3) so a single place is deep-linkable and shareable.
  const focusCell = useMemo<Cell | null>(() => {
    if (!focus) return null;
    const byId = focus.h3 ? cells.find((c) => c.h3_r10 === focus.h3) : null;
    if (byId) return byId;
    return cells.find((c) => Math.abs(c.lat - focus.lat) < 1e-5 && Math.abs(c.lon - focus.lon) < 1e-5) ?? null;
  }, [focus, cells]);
  const onFocusClickRef = useRef<(() => void) | null>(null);
  onFocusClickRef.current = focusCell ? () => onFocusOpenRef.current?.(focusCell) : null;
  useEffect(() => {
    const engine = engineRef.current;
    if (!engine || status !== "ready") return;
    if (!focus) {
      engine.setFocus(null);
      return;
    }
    engine.setView([focus.lat, focus.lon], Math.max(engine.getZoom(), 17));
    const esc = (s: string) => s.replace(/[&<>"]/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[m] as string));
    let peek = "";
    if (!modalOpen && focusCell) {
      const name = esc(cellLabel(focusCell));
      const word = esc(priorityLabel(focusCell).word);
      peek =
        `<div class="cl-peek"><div class="rounded-lg border bg-background/95 px-2.5 py-1.5 text-center shadow-lg backdrop-blur">` +
        `<div class="text-[11px] font-bold leading-tight">${name}</div>` +
        `<div class="text-[10px] text-muted-foreground">${word} · priority ${Math.round(priorityScore(focusCell))} · PIC ${Math.round(focusCell.pic_score)}</div>` +
        `<div class="text-[9px] font-medium text-primary">tap for details</div>` +
        `</div></div>`;
    } else if (!modalOpen) {
      peek = `<div class="cl-peek"><div class="rounded-lg border bg-background/95 px-2.5 py-1 text-[10px] font-medium text-primary shadow-lg backdrop-blur">tap for details</div></div>`;
    }
    const html = `<div class="cl-focus"><span class="cl-wave"></span><span class="cl-wave"></span><span class="cl-wave"></span><span class="cl-core"></span>${peek}</div>`;
    engine.setFocus({ lat: focus.lat, lon: focus.lon, html, onClick: () => onFocusClickRef.current?.() });
  }, [focus, focusCell, modalOpen, status]);
  useEffect(() => {
    const engine = engineRef.current;
    if (engine && status === "ready" && userLocation && !centeredRef.current) {
      engine.setView(userLocation, Math.max(engine.getZoom(), 14));
      centeredRef.current = true;
    }
  }, [userLocation, status]);

  // ---- traffic tiles ------------------------------------------------------
  useEffect(() => {
    const engine = engineRef.current;
    if (engine && status === "ready" && engine.supportsTraffic) engine.setTraffic(trafficOn);
  }, [trafficOn, status]);

  // ---- live-traffic layer: tell the owner to (re)fetch (debounced) --------
  useEffect(() => {
    if (!liveTrafficEnabled) return;
    const t = setTimeout(() => onLiveTrafficRef.current?.(liveOn, liveZones), 400);
    return () => clearTimeout(t);
  }, [liveOn, liveZones, liveTrafficEnabled]);

  // ---- live-traffic layer: draw the severity-coloured road segments -------
  // Keep cached road geometry visible whenever the operator turns the layer on.
  // Only hotspot DOT colour overrides are limited to the exact current lens; the
  // road layer itself is a cached context overlay and should not vanish while the
  // shift clock is being scrubbed.
  useEffect(() => {
    const engine = engineRef.current;
    if (!engine || status !== "ready") return;
    engine.setTrafficLines?.(liveOn ? liveTraffic?.segments ?? [] : []);
  }, [liveOn, liveTraffic, status]);

  // ---- keep sized on layout/viewport changes ------------------------------
  useEffect(() => {
    const onResize = () => engineRef.current?.invalidate();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const trafficAvailable = info?.supportsTraffic ?? false;
  const blindCount = useMemo(() => display.filter(isBlindSpot).length, [display]);

  const panel = (
    <LayersPanel
      simple={simple}
      setSimple={setSimple}
      hourActivity={hourActivity}
      setHourActivity={setHourActivity}
      enableComplaint={enableComplaint}
      pickMode={pickMode}
      onPickModeChange={onPickModeChange}
      showRings={showRings}
      setShowRings={setShowRings}
      blindCount={blindCount}
      showEvidence={showEvidence}
      setShowEvidence={setShowEvidence}
      hasEvidence={Boolean(evidence?.length)}
      replayOn={replayOn}
      setReplayOn={(v) => {
        setReplayOn(v);
        setPlaying(v);
      }}
      colorMode={colorMode}
      setColorMode={setColorMode}
      showHeat={showHeat}
      setShowHeat={setShowHeat}
      trafficOn={trafficOn}
      setTrafficOn={setTrafficOn}
      trafficAvailable={trafficAvailable}
      hasRoutes={Boolean(routes?.length)}
      showRoutes={showRoutes}
      setShowRoutes={setShowRoutes}
      info={info}
      liveTrafficEnabled={liveTrafficEnabled}
      liveOn={liveOn}
      setLiveOn={setLiveOn}
      liveZones={liveZones}
      setLiveZones={setLiveZones}
      liveLoading={Boolean(liveTraffic?.loading)}
      liveIsLive={Boolean(liveTraffic?.live)}
      liveCoverage={liveTraffic?.coveragePct ?? 0}
    />
  );

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

      {/* lens status chip — what the heatmap is showing. Citizens get a plain
          label; operational roles (police/govt) see how many zones are moving. */}
      {status === "ready" && (audience === "citizen" || lens?.badge) && (
        <div className="pointer-events-none absolute left-1/2 top-3 z-[500] flex max-w-[min(90%,38rem)] -translate-x-1/2 flex-wrap items-center justify-center gap-x-2 gap-y-0.5 rounded-full border bg-background/95 px-3 py-1 text-[11px] shadow-md backdrop-blur">
          {audience === "citizen" ? (
            <span className={cn("inline-flex items-center gap-1 font-medium", lens?.learningAdjusted ? "text-primary" : "text-muted-foreground")}>
              {lens?.learningAdjusted ? <Sparkles className="h-3 w-3" /> : <History className="h-3 w-3" />}
              {source === "forecast" ? "Forecast for the day" : "Parking hotspots near you"}
            </span>
          ) : (
            <>
              <span className={cn("inline-flex items-center gap-1 font-medium", lens?.learningAdjusted ? "text-primary" : "text-muted-foreground")}>
                {lens?.learningAdjusted ? <Sparkles className="h-3 w-3" /> : <History className="h-3 w-3" />}
                {lens?.badge}
              </span>
              {lens?.learningAdjusted && ((lens.nAdjusted ?? 0) > 0 || (lens.nEmerging ?? 0) > 0) ? (
                <span className="text-muted-foreground">▲ {lens.nAdjusted ?? 0} adjusting · ◆ {lens.nEmerging ?? 0} emerging</span>
              ) : null}
            </>
          )}
        </div>
      )}

      {/* layers FAB + panel (desktop = floating card · mobile = bottom sheet) */}
      <div className="absolute right-3 top-3 z-[600] flex flex-col items-end gap-2">
        <button
          onClick={() => setPanelOpen((o) => !o)}
          className="flex h-10 w-10 items-center justify-center rounded-full border bg-background/95 text-foreground shadow-md backdrop-blur hover:bg-accent"
          aria-label="Map layers & view"
          title="Map layers & view"
        >
          <Layers className="h-5 w-5" />
        </button>
        {panelOpen && !isMobile && (
          // Outer wrapper: flex column, min-h-0 + overflow-hidden so the INNER list
          // can shrink and scroll instead of pushing the panel taller (the recurring
          // overflow bug). No fixed height here — the bound lives on the inner list.
          <div className="flex min-h-0 w-72 flex-col overflow-hidden animate-slide-up rounded-xl border bg-background/97 p-3 text-sm shadow-xl backdrop-blur">
            <div className="mb-1 flex shrink-0 items-center justify-between">
              <span className="text-xs font-bold">Map layers &amp; view</span>
              <button onClick={() => setPanelOpen(false)} className="text-muted-foreground hover:text-foreground" aria-label="Close">
                <X className="h-4 w-4" />
              </button>
            </div>
            {/* INNER scroll list: bounded max-height + overflow-y-auto DIRECTLY here so
                it always scrolls inside the drawer, regardless of the flex chain. */}
            <div className="-mr-1 min-h-0 max-h-[min(60vh,28rem)] flex-1 overflow-y-auto overflow-x-hidden pr-1">{panel}</div>
          </div>
        )}
      </div>

      {/* mobile bottom sheet for the layers panel — flex column with a bounded height;
          the INNER list scrolls (min-h-0 + overflow-y-auto) so a long list never
          crops, and the sheet pads for the safe-area / bottom nav. */}
      {panelOpen && isMobile && (
        <>
          <div className="fixed inset-0 z-[1100] bg-black/40 backdrop-blur-sm" onClick={() => setPanelOpen(false)} />
          <div className="fixed inset-x-0 bottom-0 z-[1101] flex max-h-[80vh] flex-col animate-slide-up rounded-t-2xl border-t bg-background px-4 pb-[max(1.25rem,env(safe-area-inset-bottom))] pt-3 shadow-2xl">
            <div className="mx-auto mb-2 h-1 w-10 shrink-0 rounded-full bg-border" />
            <div className="mb-1 flex shrink-0 items-center justify-between">
              <span className="text-sm font-bold">Map layers &amp; view</span>
              <button onClick={() => setPanelOpen(false)} className="text-muted-foreground hover:text-foreground" aria-label="Close">
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="-mr-1 min-h-0 flex-1 overflow-y-auto overflow-x-hidden pr-1">{panel}</div>
          </div>
        </>
      )}

      {/* pick-mode hint */}
      {pickMode && status === "ready" && (
        <div className="pointer-events-none absolute left-1/2 top-14 z-[500] -translate-x-1/2 rounded-full border bg-background/95 px-3 py-1.5 text-sm shadow-md backdrop-blur">
          Tap the map to drop your complaint at that spot
        </div>
      )}

      {/* hour-of-day activity caption — collapsible */}
      {hourActivity && !replayOn && status === "ready" && (
        <div className={cn("absolute left-1/2 z-[500] w-[min(92%,30rem)] -translate-x-1/2", bottomCls)}>
          <MapPanel title="Hour-of-day activity" open={captionOpen} onToggle={() => setCaptionOpen((o) => !o)}>
            <p className="text-[11px] leading-snug">
              Circle size = MODELED typical congestion at the selected hour (drag the time slider). Ticket counts never
              vary by hour — this is the modeled commute curve, not measured traffic.
            </p>
          </MapPanel>
        </div>
      )}

      {/* historical replay controls (weekday cycle) */}
      {replayOn && status === "ready" && (
        <div className={cn("absolute left-1/2 z-[500] w-[min(92%,30rem)] -translate-x-1/2 rounded-lg border bg-background/95 px-3 py-2 shadow-md backdrop-blur", bottomCls)}>
          <div className="flex items-center justify-between">
            <b className="text-sm">Historical replay</b>
            <span className="num text-sm font-semibold text-primary">{DOW_LONG[replayIdx]}</span>
          </div>
          <div className="mt-1.5 flex items-center gap-2">
            <button onClick={() => setPlaying((p) => !p)} className="flex h-7 w-7 items-center justify-center rounded-md border bg-background hover:bg-accent" aria-label={playing ? "Pause" : "Play"}>
              {playing ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
            </button>
            <input
              type="range"
              min={0}
              max={6}
              value={replayIdx}
              onChange={(e) => {
                setPlaying(false);
                setReplayIdx(+e.target.value);
              }}
              className="flex-1 accent-primary"
              aria-label="Weekday"
            />
            <select aria-label="Replay speed" value={speed} onChange={(e) => setSpeed(+e.target.value)} className="rounded-md border bg-background px-1.5 py-1 text-xs">
              <option value={1600}>0.5×</option>
              <option value={900}>1×</option>
              <option value={450}>2×</option>
            </select>
          </div>
          <p className="mt-1 text-[10px] leading-tight text-muted-foreground">
            Recorded day-of-week propensity (ticket COUNTS are day-of-week — upload time, not parking time). Not live
            traffic; strategic ranking is unchanged.
          </p>
        </div>
      )}

      {/* recenter on user */}
      {userLocation && status === "ready" && (
        <button
          onClick={() => engineRef.current?.setView(userLocation, Math.max(engineRef.current.getZoom(), 15))}
          className={cn("absolute right-3 z-[500] flex h-10 w-10 items-center justify-center rounded-full border bg-background/95 text-primary shadow-md backdrop-blur hover:bg-accent", bottomCls)}
          aria-label="Recenter on my location"
          title="Recenter on my location"
        >
          <Crosshair className="h-5 w-5" />
        </button>
      )}

      {/* legend — its own collapsible accordion panel (header toggle) */}
      {!replayOn && status === "ready" && (
        <div className={cn("absolute left-3 z-[500] w-[min(20rem,calc(100%-5rem))]", bottomCls)}>
          <MapPanel
            title={<><Palette className="h-3.5 w-3.5 text-primary" /> Legend</>}
            open={legendOpen}
            onToggle={() => setLegendOpen((o) => !o)}
          >
            <Legend colorMode={colorMode} source={source} hourActivity={hourActivity} showRings={showRings} showEvidence={showEvidence} />
          </MapPanel>
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Collapsible floating map panel (accordion). Header toggles a bounded, scrollable
// body so legends/captions never crop the map. pointer-events-auto so the header is
// always tappable even when the wrapper is positioned over the map.
function MapPanel({
  title,
  open,
  onToggle,
  children,
}: {
  title: React.ReactNode;
  open: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="pointer-events-auto flex min-h-0 flex-col overflow-hidden rounded-lg border bg-background/95 text-[11px] shadow-md backdrop-blur">
      <button
        onClick={onToggle}
        aria-expanded={open ? "true" : "false"}
        className="flex w-full shrink-0 items-center justify-between gap-2 px-3 py-1.5 text-left font-semibold"
      >
        <span className="flex items-center gap-1.5">{title}</span>
        <ChevronDown className={cn("h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform", open ? "rotate-180" : "")} />
      </button>
      {open && <div className="min-h-0 max-h-[40vh] overflow-y-auto px-3 pb-2">{children}</div>}
    </div>
  );
}

// --------------------------------------------------------------------------- //
function ToggleRow({
  label,
  hint,
  checked,
  onChange,
  disabled,
}: {
  label: React.ReactNode;
  hint?: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <label className={cn("flex cursor-pointer items-center justify-between gap-2 py-1.5", disabled && "cursor-not-allowed opacity-50")}>
      <span className="flex flex-col">
        <span className="text-[13px]">{label}</span>
        {hint && <span className="text-[10px] leading-tight text-muted-foreground">{hint}</span>}
      </span>
      <Switch checked={checked} onCheckedChange={onChange} disabled={disabled} />
    </label>
  );
}

interface PanelProps {
  simple: boolean;
  setSimple: (v: boolean) => void;
  hourActivity: boolean;
  setHourActivity: (v: boolean) => void;
  enableComplaint: boolean;
  pickMode: boolean;
  onPickModeChange?: (v: boolean) => void;
  showRings: boolean;
  setShowRings: (v: boolean) => void;
  blindCount: number;
  showEvidence: boolean;
  setShowEvidence: (v: boolean) => void;
  hasEvidence: boolean;
  replayOn: boolean;
  setReplayOn: (v: boolean) => void;
  colorMode: ColorMode;
  setColorMode: (v: ColorMode) => void;
  showHeat: boolean;
  setShowHeat: (v: boolean) => void;
  trafficOn: boolean;
  setTrafficOn: (v: boolean) => void;
  trafficAvailable: boolean;
  hasRoutes: boolean;
  showRoutes: boolean;
  setShowRoutes: (v: boolean) => void;
  info: { label: string; priority: number; supportsTraffic: boolean } | null;
  liveTrafficEnabled: boolean;
  liveOn: boolean;
  setLiveOn: (v: boolean) => void;
  liveZones: number;
  setLiveZones: (v: number) => void;
  liveLoading: boolean;
  liveIsLive: boolean;
  liveCoverage: number;
}

function LayersPanel(p: PanelProps) {
  return (
    <Accordion type="multiple" defaultValue={["traffic", "view", "overlays", "color"]} className="w-full">
      {p.liveTrafficEnabled && (
        <AccordionItem value="traffic">
          <AccordionTrigger>Live traffic</AccordionTrigger>
          <AccordionContent>
            <ToggleRow
              label="Show live traffic"
              hint="busy streets · updates every 15 min"
              checked={p.liveOn}
              onChange={p.setLiveOn}
            />
            {p.liveOn && (
              <>
                <div className="flex items-center gap-2 py-1.5">
                  <span className="text-[13px]">Monitored zones</span>
                  <input
                    type="range"
                    min={10}
                    max={20}
                    step={1}
                    value={p.liveZones}
                    onChange={(e) => p.setLiveZones(+e.target.value)}
                    className="flex-1 accent-primary"
                    aria-label="Monitored zones (10–20)"
                  />
                  <span className="num w-6 text-right text-xs font-semibold">{p.liveZones}</span>
                </div>
                <p className="text-[10px] leading-tight text-muted-foreground">
                  {p.liveLoading
                    ? "Updating traffic…"
                    : p.liveIsLive
                      ? `${p.liveCoverage}% of zones covered. Severity = 1 − free-flow / travel-time.`
                      : "Severity = modeled day×hour congestion."}
                </p>
                <div className="mt-1 flex items-center gap-2 text-[10px] text-muted-foreground">
                  <span>busy</span>
                  <span className="h-1.5 flex-1 rounded-full" style={{ background: "linear-gradient(90deg,#16a34a,#facc15,#f97316,#dc2626)" }} />
                  <span>severe</span>
                </div>
              </>
            )}
          </AccordionContent>
        </AccordionItem>
      )}

      <AccordionItem value="view">
        <AccordionTrigger>View mode</AccordionTrigger>
        <AccordionContent>
          <ToggleRow label="Simple view" hint="P1 / P2 priority only" checked={p.simple} onChange={p.setSimple} />
          <ToggleRow label="Hour-of-day activity" hint="size by modeled congestion at the hour" checked={p.hourActivity} onChange={p.setHourActivity} />
          {p.enableComplaint && (
            <ToggleRow label="File complaint" hint="tap the map to drop a report" checked={p.pickMode} onChange={(v) => p.onPickModeChange?.(v)} />
          )}
        </AccordionContent>
      </AccordionItem>

      <AccordionItem value="overlays">
        <AccordionTrigger>Overlays</AccordionTrigger>
        <AccordionContent>
          <ToggleRow label={`Evening blind-spot rings${p.blindCount ? ` (${p.blindCount})` : ""}`} hint="high-priority · under-observed" checked={p.showRings} onChange={p.setShowRings} />
          <ToggleRow label="Evidence points" hint="recorded tickets / reports" checked={p.showEvidence} onChange={p.setShowEvidence} disabled={!p.hasEvidence} />
          <ToggleRow label="Historical replay" hint="day-of-week cycle (upload time)" checked={p.replayOn} onChange={p.setReplayOn} />
          {p.hasRoutes && <ToggleRow label="Dispatch route" hint="optimiser patrol stops" checked={p.showRoutes} onChange={p.setShowRoutes} />}
        </AccordionContent>
      </AccordionItem>

      <AccordionItem value="color">
        <AccordionTrigger>Color zones by</AccordionTrigger>
        <AccordionContent>
          <select
            aria-label="Color zones by"
            value={p.colorMode}
            onChange={(e) => p.setColorMode(e.target.value as ColorMode)}
            className="w-full rounded-md border bg-background px-2 py-1.5 text-sm"
          >
            {COLOR_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <p className="mt-1 text-[10px] leading-tight text-muted-foreground">
            green → amber → red = priority / PIC / modeled flow-impact tier — NOT measured congestion.
          </p>
        </AccordionContent>
      </AccordionItem>

      <AccordionItem value="base">
        <AccordionTrigger>Base map &amp; layers</AccordionTrigger>
        <AccordionContent>
          <ToggleRow label="Hourly heatmap" hint="modeled typical congestion" checked={p.showHeat} onChange={p.setShowHeat} />
          {p.trafficAvailable ? (
            <ToggleRow label="Live traffic tiles" hint="provider live-traffic layer" checked={p.trafficOn} onChange={p.setTrafficOn} />
          ) : (
            <div className="flex items-center justify-between gap-2 py-1.5 text-[13px] text-muted-foreground">
              <span>Live traffic tiles</span>
              <span className="rounded bg-muted px-1.5 py-0.5 text-[10px]">basemap only</span>
            </div>
          )}
          <p className="text-[10px] leading-tight text-muted-foreground">
            Live-traffic feed isn't provisioned on this Mappls account — the hourly heatmap is the modeled
            typical-congestion view.
          </p>
          {p.info && (
            <div className="mt-1.5 text-[10px] text-muted-foreground">
              Basemap: <b>{p.info.label}</b> (source {p.info.priority}/{PROVIDER_TOTAL})
            </div>
          )}
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  );
}

function Legend({
  colorMode,
  source,
  hourActivity,
  showRings,
  showEvidence,
}: {
  colorMode: ColorMode;
  source: "live" | "forecast";
  hourActivity: boolean;
  showRings: boolean;
  showEvidence: boolean;
}) {
  return (
    <div className="flex flex-col gap-1">
      {colorMode === "source" ? (
        (["live", "mappls_typical", "modeled"] as const).map((s) => (
          <span key={s} className="flex items-center gap-1.5">
            <i className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: { live: "#16a34a", mappls_typical: "#f59e0b", modeled: "#4f7fd6" }[s] }} />
            {({ live: "Current", mappls_typical: "Typical", modeled: "Modeled" } as const)[s]}
          </span>
        ))
      ) : colorMode === "tier" ? (
        <div className="flex items-center gap-2">
          {(["P1", "P2", "P3", "P4"] as const).map((t) => (
            <span key={t} className="flex items-center gap-1">
              <i className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: tierColor(t) }} /> {t}
            </span>
          ))}
        </div>
      ) : (
        <>
          <div className="font-medium">
            {colorMode === "flow" ? "Flow impact (modeled proxy)" : colorMode === "operational" ? "Operational priority" : source === "forecast" ? "Forecast intensity" : "PIC intensity"}
          </div>
          <div
            className="h-2 w-full rounded-full"
            style={{ background: colorMode === "flow" ? `linear-gradient(90deg,${flowColor(5)},${flowColor(35)},${flowColor(55)},${flowColor(75)},${flowColor(95)})` : "linear-gradient(90deg,#16a34a,#84cc16,#facc15,#f97316,#dc2626)" }}
          />
          <div className="flex justify-between text-muted-foreground">
            <span>low</span>
            <span>high</span>
          </div>
          <div className="text-[10px] text-muted-foreground">
            Zones below {V1_CIRCLE_VISIBLE_FLOOR}% active score are hidden for this time lens.
          </div>
        </>
      )}
      {showRings && (
        <span className="flex items-center gap-1.5">
          <i className="inline-block h-2.5 w-2.5 rounded-full border border-dashed border-[#d97706]" /> evening blind spot
        </span>
      )}
      {showEvidence && (
        <span className="flex items-center gap-1.5">
          <i className="inline-block h-1.5 w-1.5 rounded-full bg-slate-500" /> evidence point
        </span>
      )}
      <span className="flex items-center gap-1.5">
        <i className="inline-block h-2.5 w-2.5 rounded-full border-2 border-white bg-[#2563eb] shadow" /> reported incident (long-press map)
      </span>
      <div className="text-[10px] text-muted-foreground">{hourActivity ? "size = modeled congestion @ hour" : "size = obstruction pressure"} · modeled, not measured</div>
    </div>
  );
}
