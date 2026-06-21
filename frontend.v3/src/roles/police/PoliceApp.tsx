import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Map as MapIcon, ListChecks, Flame, Plus } from "lucide-react";
import { AppShell, type NavItem } from "@/components/AppShell";
import { ClearLaneMap, type MapPin } from "@/components/map/ClearLaneMap";
import { TimeControl, type TimeValue } from "@/components/TimeControl";
import { CellDrawer } from "@/components/CellDrawer";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { toast } from "@/components/toast";
import { TicketTable } from "./TicketTable";
import { HotspotsPanel } from "./HotspotsPanel";
import { CreateTicketDialog } from "./CreateTicketDialog";
import { ResolveDialog } from "./ResolveDialog";
import { useMapKey } from "@/hooks/useConfig";
import { useMapData } from "@/hooks/useMapData";
import { useIsMobile } from "@/hooks/useMediaQuery";
import { getDispatchPlan, getStations, getTickets, patchTicket, postTicket } from "@/lib/api";
import { getAuth, logout } from "@/lib/auth";
import { num } from "@/lib/format";
import type { Cell, DispatchPlan, ResolveInput, Station, Ticket, TicketInput } from "@/lib/types";

const KIND_PIN: Record<string, string> = {
  citizen_complaint: "#ea580c",
  police_ticket: "#2563eb",
  chalan: "#9333ea",
};

export function PoliceApp() {
  const navigate = useNavigate();
  const auth = getAuth();
  const stationName = auth?.name ?? "";
  const mapKey = useMapKey();
  const isMobile = useIsMobile();

  const [tab, setTab] = useState<"map" | "queue" | "hotspots">("map");
  const [time, setTime] = useState<TimeValue>({ when: "now", hour: 18 });
  const { data } = useMapData(time.when, time.hour);

  const [station, setStation] = useState<Station | null>(null);
  const [plan, setPlan] = useState<DispatchPlan | null>(null);
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [selected, setSelected] = useState<Cell | null>(null);
  const [flyTo, setFlyTo] = useState<[number, number] | null>(null);
  const [createFor, setCreateFor] = useState<{ open: boolean; cell: Cell | null }>({ open: false, cell: null });
  const [resolving, setResolving] = useState<Ticket | null>(null);
  const [centered, setCentered] = useState(false);

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
    { key: "queue", label: "Queue", icon: <ListChecks className="h-5 w-5" /> },
    { key: "hotspots", label: "Hotspots", icon: <Flame className="h-5 w-5" /> },
  ];

  return (
    <AppShell
      roleLabel={`Police · ${stationName}`}
      nav={nav}
      active={tab}
      onNav={(k) => setTab(k as typeof tab)}
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
            mapKey={mapKey}
            flyTo={flyTo}
            onCellClick={setSelected}
            routes={route ? [route] : undefined}
            pins={pins}
            defaultZoom={13}
          />
          <div className="absolute left-2 top-2 z-[500] w-[min(20rem,calc(100%-4.5rem))]">
            <TimeControl value={time} onChange={setTime} />
            <p className="mt-1.5 px-1 text-[11px] text-muted-foreground">
              Switch to Tomorrow to pre-plan deployment. Pins = open reports/tickets.
            </p>
          </div>
        </div>
      )}

      {tab === "queue" && (
        <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6">
          <StationStats station={station} openCount={openCount} cells={cells.length} />
          <TicketTable tickets={tickets} onResolve={setResolving} onCreate={() => setCreateFor({ open: true, cell: null })} onRowFocus={(t) => {
            if (t.lat != null && t.lon != null) {
              setFlyTo([t.lat, t.lon]);
              setTab("map");
            }
          }} />
        </div>
      )}

      {tab === "hotspots" && (
        <div className="mx-auto max-w-5xl space-y-4 p-4 sm:p-6">
          <StationStats station={station} openCount={openCount} cells={cells.length} />
          <HotspotsPanel
            cells={cells}
            route={route}
            onFocus={(c) => {
              setFlyTo([c.lat, c.lon]);
              setTab("map");
            }}
          />
        </div>
      )}

      <CellDrawer cell={selected} side={isMobile ? "bottom" : "right"} onClose={() => setSelected(null)}>
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

      <CreateTicketDialog
        open={createFor.open}
        onClose={() => setCreateFor({ open: false, cell: null })}
        station={stationName}
        cell={createFor.cell}
        onCreate={handleCreate}
      />
      <ResolveDialog ticket={resolving} onClose={() => setResolving(null)} onResolve={handleResolve} />
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
