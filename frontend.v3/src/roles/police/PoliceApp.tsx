import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Map as MapIcon, ListChecks, Flame, Plus, Waypoints, MoonStar, Shield } from "lucide-react";
import { AppShell, type NavItem } from "@/components/AppShell";
import { ClearLaneMap, type MapPin } from "@/components/map/ClearLaneMap";
import type { TrafficLineSpec } from "@/components/map/engines/types";
import { TimeControl, type TimeValue } from "@/components/TimeControl";
import { CellDrawer } from "@/components/CellDrawer";
import { CellTable } from "@/components/CellTable";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { toast } from "@/components/toast";
import { TicketTable } from "./TicketTable";
import { HotspotsPanel } from "./HotspotsPanel";
import { CreateTicketDialog } from "./CreateTicketDialog";
import { IncidentReporter, type IncidentReporterHandle } from "@/components/IncidentReporter";
import { ResolveDialog } from "./ResolveDialog";
import { ForceCommand } from "./ForceCommand";
import { useMapData } from "@/hooks/useMapData";
import { useMapFocus } from "@/hooks/useMapFocus";
import { useRoster } from "@/hooks/useRoster";
import { useIsMobile } from "@/hooks/useMediaQuery";
import { assignDispatch, getDispatchPlan, getPoliceLiveTraffic, getStations, getTickets, patchTicket, postTicket } from "@/lib/api";
import { getAuth, logout } from "@/lib/auth";
import { num } from "@/lib/format";
import { isBlindSpot, priorityScore, severityColor } from "@/lib/signals";
import type { Cell, DispatchPlan, LiveTrafficPayload, ResolveInput, Station, Ticket, TicketInput } from "@/lib/types";

type Tab = "map" | "dispatch" | "queue" | "hotspots" | "flow" | "blind";

const KIND_PIN: Record<string, string> = {
  citizen_complaint: "#2563eb", // reported incidents -> blue markers
  police_ticket: "#2563eb",
  chalan: "#9333ea",
};

// Police map: show the station's TOP-N hotspot points (by PIC), not the whole set.
const MAP_TOP_N = 20;

function istHourNow(): number {
  return Math.floor((Date.now() / 3_600_000 + 5.5) % 24);
}

function activeCellScore(c: Cell): number {
  return c.activity_score ?? c.forecast_intensity ?? c.display_score ?? c.operational_priority ?? priorityScore(c);
}

export function PoliceApp() {
  const navigate = useNavigate();
  const auth = getAuth();
  const stationName = auth?.name ?? "";
  const slug = auth?.scope ?? "";
  const isMobile = useIsMobile();

  const [tab, setTab] = useState<Tab>("map");
  const [time, setTime] = useState<TimeValue>(() => ({ when: "now", hour: istHourNow() }));
  const { data } = useMapData(time.when, time.hour, time.date);

  const [station, setStation] = useState<Station | null>(null);
  const [plan, setPlan] = useState<DispatchPlan | null>(null);
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [selected, setSelected] = useState<Cell | null>(null);
  const { focus, setFocus } = useMapFocus();
  const [flyTo, setFlyTo] = useState<[number, number] | null>(null);
  const [createFor, setCreateFor] = useState<{ open: boolean; cell: Cell | null }>({ open: false, cell: null });
  const [resolving, setResolving] = useState<Ticket | null>(null);
  const [centered, setCentered] = useState(false);
  const reportRef = useRef<IncidentReporterHandle>(null);

  const refreshTickets = useCallback(() => {
    getTickets({ station: stationName, limit: 500 }).then(setTickets).catch(() => {});
  }, [stationName]);

  useEffect(() => {
    getStations().then((list) => setStation(list.find((s) => s.station === stationName) ?? null));
    getDispatchPlan().then(setPlan);
    refreshTickets();
  }, [stationName, refreshTickets]);

  // jurisdiction cells + center the camera on the station once
  const cells = useMemo(() => (data?.cells ?? []).filter((c) => c.police_station === stationName), [data, stationName]);
  useEffect(() => {
    if (!centered && station) {
      setFlyTo([station.lat, station.lon]);
      setCentered(true);
    }
  }, [station, centered]);

  const route = useMemo(() => plan?.routes.find((r) => r.station === stationName) ?? null, [plan, stationName]);

  // ---- live-traffic layer (Avni's Phase-3 congestion, on the main map) ------
  // Lazy: only fetches when the operator turns the layer on in the Layers accordion.
  // The backend caches per (station, zones) for 15 min, so toggling is cheap.
  const [traffic, setTraffic] = useState<LiveTrafficPayload | null>(null);
  const [trafficLoading, setTrafficLoading] = useState(false);
  const trafficReq = useRef(0);
  const handleLiveTraffic = useCallback(
    (on: boolean, zones: number) => {
      if (!on || !stationName) {
        setTraffic(null);
        return;
      }
      const id = ++trafficReq.current;
      setTrafficLoading(true);
      getPoliceLiveTraffic(stationName, zones, false)
        .then((d) => trafficReq.current === id && setTraffic(d))
        .catch(() => trafficReq.current === id && setTraffic(null))
        .finally(() => trafficReq.current === id && setTrafficLoading(false));
    },
    [stationName],
  );
  const trafficSegments = useMemo<TrafficLineSpec[]>(
    () =>
      (traffic?.zones ?? []).map((z) => ({
        id: `tr-${z.h3_r10}`,
        points: z.segment,
        color: severityColor(z.congestion_severity),
        tooltip:
          `${z.congestion_label ?? "—"} · severity ${(z.congestion_severity ?? 0).toFixed(2)}` +
          (z.travel_time_index != null ? ` · TTI ${z.travel_time_index.toFixed(2)}×` : ""),
      })),
    [traffic],
  );
  // h3 -> live severity colour, so the monitored hotspot dots recolour by congestion
  // (Avni's dot technique) when the live layer is on.
  const liveSeverityByCell = useMemo<Record<string, string>>(
    () => Object.fromEntries((traffic?.zones ?? []).map((z) => [z.h3_r10, severityColor(z.congestion_severity)])),
    [traffic],
  );

  // Declutter the map: show the station's TOP active-time cells, while making sure
  // blind spots / emerging cells / user-marked cells can still surface.
  const openTicketCells = useMemo(() => new Set(tickets.filter((t) => t.status === "open" && t.cell).map((t) => t.cell as string)), [tickets]);
  const mapCells = useMemo(() => {
    const important = cells.filter((c) => c.emerging || isBlindSpot(c) || openTicketCells.has(c.h3_r10));
    const ranked = [...cells].sort((a, b) => activeCellScore(b) - activeCellScore(a));
    const byId = new Map<string, Cell>();
    [...important.sort((a, b) => activeCellScore(b) - activeCellScore(a)), ...ranked].forEach((c) => {
      if (byId.size < MAP_TOP_N || byId.has(c.h3_r10)) byId.set(c.h3_r10, c);
    });
    return [...byId.values()].slice(0, MAP_TOP_N).sort((a, b) => activeCellScore(b) - activeCellScore(a));
  }, [cells, openTicketCells]);

  // station roster (live or offline seed) — shared by Force Command + the ticket
  // "assign officer" dropdown so an assignee always comes from this station's roster.
  const rosterApi = useRoster(slug || null, { name: stationName, lat: station?.lat, lon: station?.lon, nZones: cells.length || station?.n_cells });
  const rosterOfficers = rosterApi.roster?.officers ?? [];

  const pins = useMemo<MapPin[]>(
    () =>
      tickets
        .filter((t) => t.status === "open" && t.lat != null && t.lon != null)
        .map((t) => ({
          key: t.id,
          lat: t.lat as number,
          lon: t.lon as number,
          color: KIND_PIN[t.kind] ?? "#ea580c",
          pulse: t.kind === "citizen_complaint",
          label: `${t.category ?? "Ticket"} · ${t.kind === "citizen_complaint" ? "citizen report" : "ticket"}`,
          onClick: () => setResolving(t),
        })),
    [tickets],
  );
  const evidence = useMemo<[number, number][]>(
    () => tickets.filter((t) => t.lat != null && t.lon != null).map((t) => [t.lat as number, t.lon as number]),
    [tickets],
  );

  const openCount = tickets.filter((t) => t.status === "open").length;

  async function handleCreate(input: TicketInput) {
    await postTicket(input);
    setCreateFor({ open: false, cell: null });
    refreshTickets();
    toast("Ticket created", { desc: `${input.category} logged for ${stationName}.`, tone: "success" });
  }
  async function handleResolve(id: string, body: ResolveInput) {
    await patchTicket(id, body);
    setResolving(null);
    refreshTickets();
    toast("Ticket closed", { desc: body.resolution ? "Marked resolved." : "Marked not resolved.", tone: body.resolution ? "success" : "info" });
  }

  const nav: NavItem[] = [
    { key: "map", label: "Map", icon: <MapIcon className="h-5 w-5" /> },
    { key: "dispatch", label: "Force Dispatch", icon: <Shield className="h-5 w-5" /> },
    { key: "queue", label: "Tickets", icon: <ListChecks className="h-5 w-5" /> },
    { key: "hotspots", label: "Hotspots", icon: <Flame className="h-5 w-5" /> },
    { key: "flow", label: "Road impact", icon: <Waypoints className="h-5 w-5" /> },
    { key: "blind", label: "Blind spots", icon: <MoonStar className="h-5 w-5" /> },
  ];

  // Every redirection (map dot, AI picks, dispatch queue, hotspot/flow/blind
  // tables, tickets, deep link) lands on the SAME place ripple: zoom in + "waves
  // out" + a numbers peek. Tapping the ripple opens the detail modal. The point
  // lives in the URL (?lat&lon&h3) so it is shareable.
  const focusCell = (c: Cell) => {
    setFocus({ lat: c.lat, lon: c.lon, h3: c.h3_r10 });
    setTab("map");
  };
  const focusAt = (lat: number, lon: number, h3?: string) => {
    setFocus({ lat, lon, h3 });
    setTab("map");
  };
  // Ripple tapped -> open the modal. Resolve the full cell by h3 (whole map set),
  // fall back to coords, then a minimal cell so the drawer always opens.
  const openFocus = (c: Cell) => {
    const all = data?.cells ?? [];
    const match = all.find((x) => x.h3_r10 === c.h3_r10) ?? c;
    setSelected(match);
  };
  const liveTrafficActive = time.when === "now" && time.hour === istHourNow();

  return (
    <AppShell
      roleLabel={`Police · ${stationName}`}
      nav={nav}
      active={tab}
      onNav={(k) => setTab(k as Tab)}
      onSwitchRole={() => navigate("/")}
      onLogout={() => {
        logout();
        navigate("/");
      }}
      userName={stationName}
      fill={tab === "map"}
      headerExtra={openCount > 0 ? <Badge variant="warning">{openCount} open</Badge> : undefined}
    >
      {tab === "map" && (
        <div className="absolute inset-0">
          <ClearLaneMap
            cells={mapCells}
            source={data?.source ?? "live"}
            flyTo={flyTo}
            focus={focus}
            modalOpen={Boolean(selected)}
            onCellClick={focusCell}
            onFocusOpen={openFocus}
            defaultColorMode="pic"
            onLongPress={(ll) => reportRef.current?.openAt(ll)}
            routes={route ? [route] : undefined}
            pins={pins}
            evidence={evidence}
            defaultZoom={13}
            lens={{ badge: data?.badge, nEmerging: data?.n_emerging, nAdjusted: data?.n_adjusted, learningAdjusted: data?.learning_adjusted }}
            liveTrafficEnabled
            liveTrafficDefaultOn
            liveTraffic={{ segments: trafficSegments, loading: trafficLoading, live: Boolean(traffic?.live_eta), coveragePct: traffic?.coverage_pct ?? 0 }}
            liveTrafficActive={liveTrafficActive}
            liveSeverityByCell={liveSeverityByCell}
            onLiveTraffic={handleLiveTraffic}
          />
          <div className="absolute left-2 top-2 z-[500] w-[min(20rem,calc(100%-4.5rem))]">
            <TimeControl value={time} onChange={setTime} />
          </div>
          <Button
            onClick={() => setCreateFor({ open: true, cell: null })}
            className="absolute bottom-20 right-4 z-[610] gap-2 rounded-full px-5 shadow-lg md:bottom-6"
          >
            <Plus className="h-4 w-4" /> Create ticket
          </Button>
        </div>
      )}

      {tab === "dispatch" && (
        <div className="mx-auto max-w-6xl p-4 sm:p-6">
          <ForceCommand
            slug={slug}
            stationName={stationName}
            lat={station?.lat}
            lon={station?.lon}
            cells={cells}
            canManage
            rosterApi={rosterApi}
            when={time.when}
            hour={time.hour}
            station={station}
            showTargets
            onFocus={focusAt}
            onZoneFocus={(c) => focusCell(c)}
          />
        </div>
      )}

      {tab === "queue" && (
        <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6">
          <StationStats station={station} openCount={openCount} cells={cells.length} />
          <TicketTable
            tickets={tickets}
            onResolve={setResolving}
            onCreate={() => setCreateFor({ open: true, cell: null })}
            onRowFocus={(t) => {
              if (t.lat != null && t.lon != null) {
                setFocus({ lat: t.lat, lon: t.lon, h3: t.cell ?? undefined });
                setTab("map");
              }
            }}
          />
        </div>
      )}

      {tab === "hotspots" && (
        <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6">
          <StationStats station={station} openCount={openCount} cells={cells.length} />
          <HotspotsPanel cells={cells} route={route} onFocus={focusCell} />
        </div>
      )}

      {tab === "flow" && (
        <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6">
          <StationStats station={station} openCount={openCount} cells={cells.length} />
          <CellTable cells={cells} variant="flow" onFocus={focusCell} />
        </div>
      )}

      {tab === "blind" && (
        <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6">
          <StationStats station={station} openCount={openCount} cells={cells.length} />
          <CellTable cells={cells} variant="blind" onFocus={focusCell} />
        </div>
      )}

      <CellDrawer cell={selected} cells={cells} audience="police" side={isMobile ? "bottom" : "right"} onClose={() => setSelected(null)}>
        {selected && (
          <div className="grid gap-2 sm:grid-cols-2">
            <Button
              className="w-full"
              onClick={() => {
                setCreateFor({ open: true, cell: selected });
                setSelected(null);
              }}
            >
              <Plus className="h-4 w-4" /> Create ticket here
            </Button>
            <Button
              variant="outline"
              className="w-full"
              onClick={async () => {
                const cell = selected.h3_r10;
                const r = await assignDispatch(cell);
                toast(r.ok ? "Team deployed to this spot" : r.error || "Dispatch failed", { tone: r.ok ? "success" : "warning" });
                setFlyTo([selected.lat, selected.lon]);
                setSelected(null);
                setTab("dispatch");
              }}
            >
              Dispatch
            </Button>
          </div>
        )}
      </CellDrawer>

      <CreateTicketDialog open={createFor.open} onClose={() => setCreateFor({ open: false, cell: null })} station={stationName} cell={createFor.cell} officers={rosterOfficers} onCreate={handleCreate} />
      <ResolveDialog ticket={resolving} onClose={() => setResolving(null)} onResolve={handleResolve} />
      {/* long-press the map anywhere -> report an incident (no FAB; Create-ticket is the primary) */}
      <IncidentReporter ref={reportRef} showFab={false} onFiled={refreshTickets} defaultLoc={station ? [station.lat, station.lon] : null} />
    </AppShell>
  );
}

function StationStats({ station, openCount, cells }: { station: Station | null; openCount: number; cells: number }) {
  const stats = [
    { label: "Open tickets", value: openCount },
    { label: "Cells in area", value: cells },
    { label: "Emerging", value: station?.n_emerging ?? "—" },
    { label: "Expected/wk", value: station ? num(station.weekly_expected, 0) : "—" },
  ];
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {stats.map((s) => (
        <div key={s.label} className="rounded-xl border bg-card p-3">
          <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{s.label}</div>
          <div className="num mt-1 text-2xl font-bold">{s.value}</div>
        </div>
      ))}
    </div>
  );
}
