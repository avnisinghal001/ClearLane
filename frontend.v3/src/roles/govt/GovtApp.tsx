import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  LayoutDashboard, Map as MapIcon, Radio, ListChecks, Waypoints, MoonStar,
  Building2, RefreshCw, ShieldCheck, Shield,
} from "lucide-react";
import { AppShell, type NavItem } from "@/components/AppShell";
import { ClearLaneMap, type MapPin } from "@/components/map/ClearLaneMap";
import { IncidentReporter, type IncidentReporterHandle } from "@/components/IncidentReporter";
import type { TimeValue } from "@/components/TimeControl";
import { TimeControl } from "@/components/TimeControl";
import { CellDrawer } from "@/components/CellDrawer";
import { CellTable } from "@/components/CellTable";
import { AiNextPicks } from "@/components/AiNextPicks";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { CommandMetrics } from "./CommandMetrics";
import { KpiStrip } from "./KpiStrip";
import { StationTable } from "./StationTable";
import { StationManager } from "./StationManager";
import { Analytics } from "./Analytics";
import { Scorecard } from "./Scorecard";
import { GovtPlaybook } from "./GovtPlaybook";
import { DispatchQueue } from "@/roles/police/DispatchQueue";
import { ForceCommand } from "@/roles/police/ForceCommand";
import { useMapData } from "@/hooks/useMapData";
import { useMapFocus } from "@/hooks/useMapFocus";
import { useRoster } from "@/hooks/useRoster";
import { useIsMobile } from "@/hooks/useMediaQuery";
import { getCausal, getEvaluation, getKpis, getSim, getStations, getTickets } from "@/lib/api";
import { logout } from "@/lib/auth";
import { cellTier } from "@/lib/signals";
import type { Cell, Kpis, Station, Ticket } from "@/lib/types";

/* eslint-disable @typescript-eslint/no-explicit-any */

type Tab = "overview" | "map" | "dispatch" | "queue" | "force" | "flow" | "blind" | "stations" | "loop" | "evidence";

function istHourNow(): number {
  return Math.floor((Date.now() / 3_600_000 + 5.5) % 24);
}

export function GovtApp() {
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  const [tab, setTab] = useState<Tab>("overview");
  const [time, setTime] = useState<TimeValue>(() => ({ when: "now", hour: istHourNow() }));
  const [allDay, setAllDay] = useState(true);
  const { data, refetch } = useMapData(time.when, time.hour, time.date);

  const [kpis, setKpis] = useState<Kpis | null>(null);
  const [stations, setStations] = useState<Station[]>([]);
  const [sim, setSim] = useState<any>(null);
  const [causal, setCausal] = useState<any>(null);
  const [evaluation, setEvaluation] = useState<any>(null);
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [selected, setSelected] = useState<Cell | null>(null);
  const { focus, setFocus } = useMapFocus();
  const [flyTo, setFlyTo] = useState<[number, number] | null>(null);
  const [forceSlug, setForceSlug] = useState<string>("");
  const reportRef = useRef<IncidentReporterHandle>(null);

  // reported incidents -> blue markers on the city map
  const reportPins = useMemo<MapPin[]>(
    () =>
      tickets
        .filter((t) => t.kind === "citizen_complaint" && t.status === "open" && t.lat != null && t.lon != null)
        .map((t) => ({
          key: t.id,
          lat: t.lat as number,
          lon: t.lon as number,
          color: "#2563eb",
          pulse: true,
          label: `${t.category ?? "Reported incident"} · ${t.station ?? "nearest station"}`,
        })),
    [tickets],
  );

  useEffect(() => {
    getKpis().then(setKpis);
    getStations().then(setStations);
    getSim().then(setSim);
    getCausal().then(setCausal);
    getEvaluation().then(setEvaluation);
    getTickets({ limit: 500 }).then(setTickets).catch(() => {});
  }, []);

  const cells = data?.cells ?? [];
  const evidence = useMemo<[number, number][]>(
    () => tickets.filter((t) => t.lat != null && t.lon != null).map((t) => [t.lat as number, t.lon as number]),
    [tickets],
  );
  const liveOps = useMemo(() => tickets.filter((t) => t.status === "open").length, [tickets]);

  // Force Command for a selected station (govt manages ALL stations' rosters).
  const forceStation = useMemo(() => stations.find((s) => s.slug === forceSlug) ?? stations[0] ?? null, [stations, forceSlug]);
  const forceCells = useMemo(() => cells.filter((c) => c.police_station === forceStation?.station), [cells, forceStation]);
  const forceRoster = useRoster(forceStation?.slug ?? null, {
    name: forceStation?.station,
    lat: forceStation?.lat,
    lon: forceStation?.lon,
    nZones: forceStation?.n_cells,
  });

  const p1ByStation = useMemo(() => {
    const m: Record<string, number> = {};
    for (const c of cells) if (c.police_station && cellTier(c) === "P1") m[c.police_station] = (m[c.police_station] ?? 0) + 1;
    return m;
  }, [cells]);

  const stationPins = useMemo<MapPin[]>(
    () =>
      stations
        .filter((s) => s.lat != null && s.lon != null)
        .map((s) => {
          const p1 = p1ByStation[s.station] ?? 0;
          return {
            key: s.slug,
            lat: s.lat,
            lon: s.lon,
            color: p1 >= 6 ? "#dc2626" : p1 >= 3 ? "#f97316" : "#2563eb",
            label: `${s.station} · ${p1} P1 · ${s.n_cells} cells`,
            onClick: () => setFlyTo([s.lat, s.lon]),
          };
        }),
    [stations, p1ByStation],
  );

  const nav: NavItem[] = [
    { key: "overview", label: "Command center", icon: <LayoutDashboard className="h-5 w-5" /> },
    { key: "map", label: "Command map", icon: <MapIcon className="h-5 w-5" /> },
    { key: "dispatch", label: "Dispatch AI", icon: <Radio className="h-5 w-5" /> },
    { key: "queue", label: "Priority queue", icon: <ListChecks className="h-5 w-5" /> },
    { key: "force", label: "Force Command", icon: <Shield className="h-5 w-5" /> },
    { key: "flow", label: "Flow impact", icon: <Waypoints className="h-5 w-5" /> },
    { key: "blind", label: "Blind spots", icon: <MoonStar className="h-5 w-5" /> },
    { key: "stations", label: "Stations", icon: <Building2 className="h-5 w-5" /> },
    { key: "loop", label: "Operations loop", icon: <RefreshCw className="h-5 w-5" /> },
    { key: "evidence", label: "Evidence", icon: <ShieldCheck className="h-5 w-5" /> },
  ];

  // Every redirection (map dot, AI picks, dispatch queue, priority/flow/blind
  // tables, deep link) lands on the SAME place ripple: zoom in + "waves out" + a
  // numbers peek. Tapping the ripple opens the detail modal. The point lives in
  // the URL (?lat&lon&h3) so it is shareable.
  const focusCell = (c: Cell) => {
    setFocus({ lat: c.lat, lon: c.lon, h3: c.h3_r10 });
    setTab("map");
  };
  const focusAt = (lat: number, lon: number, h3?: string) => {
    setFocus({ lat, lon, h3 });
    setTab("map");
  };
  // Ripple tapped -> open the modal (resolve the full cell by h3, else use as-is).
  const openFocus = (c: Cell) => {
    const all = data?.cells ?? [];
    setSelected(all.find((x) => x.h3_r10 === c.h3_r10) ?? c);
  };

  return (
    <AppShell
      roleLabel="Government Command"
      nav={nav}
      active={tab}
      onNav={(k) => setTab(k as Tab)}
      onSwitchRole={() => navigate("/")}
      onLogout={() => {
        logout();
        navigate("/");
      }}
      userName="City-wide"
      fill={tab === "map"}
    >
      {tab === "overview" && (
        <div className="mx-auto max-w-7xl space-y-5 p-4 sm:p-6">
          <div>
            <h2 className="text-xl font-bold">City command center</h2>
            <p className="text-sm text-muted-foreground">
              Bias-corrected parking-enforcement intelligence across {stations.length} stations. Honest by design — we never claim to measure congestion from tickets.
            </p>
          </div>
          <CommandMetrics cells={cells} kpis={kpis} liveOps={liveOps} />
          {kpis ? <KpiStrip k={kpis} /> : <div className="h-24 animate-pulse rounded-xl bg-muted" />}
          {kpis && sim && causal && <Analytics kpis={kpis} sim={sim} causal={causal} />}
        </div>
      )}

      {tab === "map" && (
        <div className="absolute inset-0">
          <ClearLaneMap
            cells={cells}
            source={data?.source ?? "live"}
            flyTo={flyTo}
            focus={focus}
            modalOpen={Boolean(selected)}
            onCellClick={focusCell}
            onFocusOpen={openFocus}
            onLongPress={(ll) => reportRef.current?.openAt(ll)}
            pins={reportPins}
            evidence={evidence}
            defaultHeat
            defaultZoom={11}
            sizeMode={allDay ? "pressure" : "intensity"}
            lens={{ badge: data?.badge, nEmerging: data?.n_emerging, nAdjusted: data?.n_adjusted, learningAdjusted: data?.learning_adjusted }}
          />
          <div className="absolute left-2 top-2 z-[500] w-[min(20rem,calc(100%-4.5rem))]">
            <TimeControl value={time} onChange={setTime} allDay={allDay} onAllDayChange={setAllDay} />
            <div className="mt-2">
              <Badge variant={data?.source === "forecast" ? "modeled" : "live"}>{data?.source === "forecast" ? "Forecast" : "Now"}</Badge>
            </div>
          </div>
          {/* government can also report — FAB at 5vh + long-press the map */}
          <IncidentReporter ref={reportRef} onFiled={() => getTickets({ limit: 500 }).then(setTickets).catch(() => {})} defaultLoc={cells[0] ? [cells[0].lat, cells[0].lon] : null} />
        </div>
      )}

      {tab === "dispatch" && (
        <div className="mx-auto max-w-6xl space-y-4 p-4 sm:p-6">
          <div>
            <h2 className="text-xl font-bold">Dispatch AI — city-wide</h2>
            <p className="text-sm text-muted-foreground">The M4 reranker fuses forecast · pressure · under-observed · congestion · reachability into one transparent number.</p>
          </div>
          <AiNextPicks station={null} when={time.when} hour={time.hour} onFocus={focusAt} title="AI next picks · city-wide" />
          <DispatchQueue stationName="" when={time.when} hour={time.hour} onFocus={focusAt} />
        </div>
      )}

      {tab === "queue" && (
        <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6">
          <CellTable cells={cells} variant="priority" onFocus={focusCell} />
        </div>
      )}

      {tab === "force" && (
        <div className="mx-auto max-w-6xl space-y-4 p-4 sm:p-6">
          <div className="flex flex-wrap items-end justify-between gap-2">
            <div>
              <h2 className="text-xl font-bold">Force Command</h2>
              <p className="text-sm text-muted-foreground">Roster, patrol board and priority×area allocation for any station. Government manages all stations; scope is enforced server-side.</p>
            </div>
            <label className="flex flex-col text-[11px] font-medium text-muted-foreground">
              Station
              <select
                aria-label="Select station"
                value={forceStation?.slug ?? ""}
                onChange={(e) => setForceSlug(e.target.value)}
                className="mt-1 h-9 min-w-[12rem] rounded-md border bg-background px-2 text-sm text-foreground"
              >
                {stations.map((s) => (
                  <option key={s.slug} value={s.slug}>
                    {s.station}
                  </option>
                ))}
              </select>
            </label>
          </div>
          {forceStation ? (
            <ForceCommand
              key={forceStation.slug}
              slug={forceStation.slug}
              stationName={forceStation.station}
              lat={forceStation.lat}
              lon={forceStation.lon}
              cells={forceCells}
              canManage
              rosterApi={forceRoster}
              when={time.when}
              hour={time.hour}
              onZoneFocus={(c) => focusCell(c)}
            />
          ) : (
            <div className="text-sm text-muted-foreground">Loading stations…</div>
          )}
        </div>
      )}

      {tab === "flow" && (
        <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6">
          <CellTable cells={cells} variant="flow" onFocus={focusCell} />
        </div>
      )}

      {tab === "blind" && (
        <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6">
          <CellTable cells={cells} variant="blind" onFocus={focusCell} />
        </div>
      )}

      {tab === "stations" && (
        <div className="mx-auto max-w-7xl space-y-4 p-4 sm:p-6">
          <div>
            <h2 className="text-xl font-bold">Stations</h2>
            <p className="text-sm text-muted-foreground">City overview, the station roster and per-station performance. Aggregated to the zone level only — never per officer.</p>
          </div>
          <Card className="overflow-hidden">
            <CardHeader className="pb-2">
              <CardTitle className="text-base">City overview — all stations</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              <div className="h-[360px]">
                <ClearLaneMap cells={cells} source={data?.source ?? "live"} flyTo={flyTo} focus={focus} modalOpen={Boolean(selected)} onCellClick={focusCell} onFocusOpen={openFocus} pins={stationPins} defaultZoom={11} sizeMode="pressure" />
              </div>
            </CardContent>
          </Card>
          <StationManager analytics={stations} onFocus={(lat, lon) => { setFlyTo([lat, lon]); setTab("map"); }} />
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Per-station performance ({stations.length})</CardTitle>
            </CardHeader>
            <CardContent>
              <StationTable stations={stations} onFocus={(s) => { setFlyTo([s.lat, s.lon]); setTab("map"); }} />
            </CardContent>
          </Card>
        </div>
      )}

      {tab === "loop" && (
        <div className="mx-auto max-w-7xl space-y-4 p-4 sm:p-6">
          <div>
            <h2 className="text-xl font-bold">Operations loop</h2>
            <p className="text-sm text-muted-foreground">How today's plan is built — and how the self-learning loop folds feedback into the next one.</p>
          </div>
          <GovtPlaybook
            kpis={kpis}
            onDone={() => {
              setTime({ when: "now", hour: new Date().getHours() });
              setAllDay(false);
              refetch();
              getKpis().then(setKpis);
            }}
          />
        </div>
      )}

      {tab === "evidence" && (
        <div className="mx-auto max-w-6xl space-y-4 p-4 sm:p-6">
          <div>
            <h2 className="text-xl font-bold">Model evidence scorecard</h2>
            <p className="text-sm text-muted-foreground">Auditable capability bars from the ML pipeline's self-grading.</p>
          </div>
          {evaluation ? <Scorecard evaluation={evaluation} /> : <div className="h-40 animate-pulse rounded-xl bg-muted" />}
        </div>
      )}

      <CellDrawer cell={selected} cells={cells} audience="govt" side={isMobile ? "bottom" : "right"} onClose={() => setSelected(null)} />
    </AppShell>
  );
}
