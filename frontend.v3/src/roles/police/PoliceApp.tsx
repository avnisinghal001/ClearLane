import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Map as MapIcon, ListChecks, Flame, Plus, Radio, Waypoints, MoonStar, Shield } from "lucide-react";
import { AppShell, type NavItem } from "@/components/AppShell";
import { ClearLaneMap, type MapPin } from "@/components/map/ClearLaneMap";
import { TimeControl, type TimeValue } from "@/components/TimeControl";
import { CellDrawer } from "@/components/CellDrawer";
import { CellTable } from "@/components/CellTable";
import { AiNextPicks } from "@/components/AiNextPicks";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { SourceBadge } from "@/components/SourceBadge";
import { toast } from "@/components/toast";
import { TicketTable } from "./TicketTable";
import { HotspotsPanel } from "./HotspotsPanel";
import { DispatchQueue } from "./DispatchQueue";
import { CreateTicketDialog } from "./CreateTicketDialog";
import { IncidentReporter, type IncidentReporterHandle } from "@/components/IncidentReporter";
import { ResolveDialog } from "./ResolveDialog";
import { ForceCommand } from "./ForceCommand";
import { useMapData } from "@/hooks/useMapData";
import { useRoster } from "@/hooks/useRoster";
import { useIsMobile } from "@/hooks/useMediaQuery";
import { getDispatchPlan, getStations, getTickets, patchTicket, postTicket } from "@/lib/api";
import { getAuth, logout } from "@/lib/auth";
import { num } from "@/lib/format";
import type { Cell, DispatchPlan, ResolveInput, Station, Ticket, TicketInput } from "@/lib/types";

type Tab = "map" | "dispatch" | "queue" | "force" | "hotspots" | "flow" | "blind";

const KIND_PIN: Record<string, string> = {
  citizen_complaint: "#2563eb", // reported incidents -> blue markers
  police_ticket: "#2563eb",
  chalan: "#9333ea",
};

export function PoliceApp() {
  const navigate = useNavigate();
  const auth = getAuth();
  const stationName = auth?.name ?? "";
  const slug = auth?.scope ?? "";
  const isMobile = useIsMobile();

  const [tab, setTab] = useState<Tab>("map");
  const [time, setTime] = useState<TimeValue>({ when: "now", hour: 18 });
  const { data } = useMapData(time.when, time.hour, time.date);

  const [station, setStation] = useState<Station | null>(null);
  const [plan, setPlan] = useState<DispatchPlan | null>(null);
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [selected, setSelected] = useState<Cell | null>(null);
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
    { key: "map", label: "Command map", icon: <MapIcon className="h-5 w-5" /> },
    { key: "force", label: "Force Command", icon: <Shield className="h-5 w-5" /> },
    { key: "dispatch", label: "Dispatch AI", icon: <Radio className="h-5 w-5" /> },
    { key: "queue", label: "Priority queue", icon: <ListChecks className="h-5 w-5" /> },
    { key: "hotspots", label: "Hotspots", icon: <Flame className="h-5 w-5" /> },
    { key: "flow", label: "Flow impact", icon: <Waypoints className="h-5 w-5" /> },
    { key: "blind", label: "Blind spots", icon: <MoonStar className="h-5 w-5" /> },
  ];

  const focusCell = (c: Cell) => {
    setFlyTo([c.lat, c.lon]);
    setTab("map");
  };

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
            cells={cells}
            source={data?.source ?? "live"}
            flyTo={flyTo}
            onCellClick={setSelected}
            onLongPress={(ll) => reportRef.current?.openAt(ll)}
            routes={route ? [route] : undefined}
            pins={pins}
            evidence={evidence}
            defaultZoom={13}
            lens={{ badge: data?.badge, nEmerging: data?.n_emerging, nAdjusted: data?.n_adjusted, learningAdjusted: data?.learning_adjusted }}
          />
          <div className="absolute left-2 top-2 z-[500] w-[min(20rem,calc(100%-4.5rem))]">
            <TimeControl value={time} onChange={setTime} />
            <div className="mt-1.5 flex items-center gap-1.5 px-1">
              <span className="text-[11px] text-muted-foreground">Congestion:</span>
              <SourceBadge source={data?.congestion_source ?? "simulated"} />
              {data?.congestion_live === false && <span className="text-[10px] text-muted-foreground">live ETA off</span>}
            </div>
            <p className="mt-1 px-1 text-[11px] text-muted-foreground">Switch to Tomorrow to pre-plan deployment. Pins = open reports/tickets.</p>
          </div>
          <Button
            onClick={() => setCreateFor({ open: true, cell: null })}
            className="absolute bottom-20 right-4 z-[610] gap-2 rounded-full px-5 shadow-lg md:bottom-6"
          >
            <Plus className="h-4 w-4" /> Create ticket
          </Button>
        </div>
      )}

      {tab === "force" && (
        <div className="mx-auto max-w-6xl p-4 sm:p-6">
          <ForceCommand slug={slug} stationName={stationName} lat={station?.lat} lon={station?.lon} cells={cells} canManage rosterApi={rosterApi} />
        </div>
      )}

      {tab === "dispatch" && (
        <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6">
          <StationStats station={station} openCount={openCount} cells={cells.length} />
          <AiNextPicks station={stationName} onFocus={(lat, lon) => { setFlyTo([lat, lon]); setTab("map"); }} title={`AI next picks · ${stationName}`} />
          <DispatchQueue stationName={stationName} onFocus={(lat, lon) => { setFlyTo([lat, lon]); setTab("map"); }} />
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
                setFlyTo([t.lat, t.lon]);
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

      <CellDrawer cell={selected} cells={cells} side={isMobile ? "bottom" : "right"} onClose={() => setSelected(null)}>
        {selected && (
          <Button
            className="w-full"
            onClick={() => {
              setCreateFor({ open: true, cell: selected });
              setSelected(null);
            }}
          >
            <Plus className="h-4 w-4" /> Create ticket here
          </Button>
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
