import { useEffect, useMemo, useState } from "react";
import { Flame, ShieldAlert, Users, Megaphone, Map as MapIcon } from "lucide-react";
import { Kpi } from "@/components/Kpi";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { RosterPanel } from "./RosterPanel";
import { PatrolBoard } from "./PatrolBoard";
import { AutoAllocatePanel } from "./AutoAllocatePanel";
import type { UseRoster } from "@/hooks/useRoster";
import { getDispatchQueue, getTickets } from "@/lib/api";
import { cellTier, isBlindSpot } from "@/lib/signals";
import type { Problem } from "@/lib/force";
import type { Cell, Officer, Ticket } from "@/lib/types";

const BLR: [number, number] = [12.9716, 77.5946];

// Force Command — the station/Inspector operations console: a station header, the
// priority/blind-spot/complaints/officers cards, the LIVE troop-deployment patrol
// board (shift-clock + auto-allocate), the priority×area allocation table and the
// members & hierarchy roster. Reusable: a station runs its own; government can run
// any station's (canManage stays true for both; scope is enforced server-side).
export function ForceCommand({
  slug,
  stationName,
  lat,
  lon,
  cells,
  canManage,
  rosterApi,
}: {
  slug: string;
  stationName: string;
  lat?: number | null;
  lon?: number | null;
  cells: Cell[];
  canManage: boolean;
  rosterApi: UseRoster;
}) {
  const { roster, loading, addOfficer, patchOfficer, removeOfficer } = rosterApi;
  const [problems, setProblems] = useState<Problem[]>([]);
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [picked, setPicked] = useState<Officer | null>(null);

  // station priority zones (from the M4 dispatch queue) -> the patrol sim's problems
  useEffect(() => {
    let alive = true;
    getDispatchQueue(slug, "now")
      .then((q) => {
        if (!alive) return;
        const probs = (q.queue ?? [])
          .filter((r) => r.lat != null && r.lon != null)
          .map((r) => ({ id: r.h3_r10, name: r.name || r.h3_r10.slice(0, 8), lat: r.lat, lon: r.lon, score: r.rerank_score }));
        setProblems(probs);
      })
      .catch(() => setProblems([]));
    return () => {
      alive = false;
    };
  }, [slug]);

  // fall back to the station's top cells when the queue is empty (offline)
  const problemsResolved = useMemo<Problem[]>(() => {
    if (problems.length) return problems;
    return cells
      .filter((c) => (c.pic_score ?? 0) > 0)
      .sort((a, b) => (b.pic_score ?? 0) - (a.pic_score ?? 0))
      .slice(0, 20)
      .map((c) => ({ id: c.h3_r10, name: `${stationName} · ${c.h3_r10.slice(0, 6)}`, lat: c.lat, lon: c.lon, score: c.pic_score ?? 0 }));
  }, [problems, cells, stationName]);

  const refreshTickets = () => getTickets({ station: stationName, limit: 500 }).then(setTickets).catch(() => {});
  useEffect(() => {
    refreshTickets();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stationName]);

  const counts = useMemo(() => {
    let p1 = 0;
    let p2 = 0;
    let blind = 0;
    for (const c of cells) {
      const t = cellTier(c);
      if (t === "P1") p1++;
      else if (t === "P2") p2++;
      if (isBlindSpot(c)) blind++;
    }
    return { p1, p2, blind };
  }, [cells]);

  const openCount = tickets.filter((t) => t.status === "open").length;
  const officers = roster?.officers ?? [];
  const center = useMemo<[number, number]>(() => {
    if (roster?.station.lat != null && roster?.station.lon != null) return [roster.station.lat, roster.station.lon];
    if (lat != null && lon != null) return [lat, lon];
    if (cells.length) return [cells[0].lat, cells[0].lon];
    return BLR;
  }, [roster, lat, lon, cells]);

  return (
    <div className="space-y-4">
      {/* station header */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 text-xl font-bold">
            <MapIcon className="h-5 w-5 text-primary" /> {stationName}
          </h2>
          <p className="text-sm text-muted-foreground">
            {cells.length} zones · {officers.length} officers · Force Command
          </p>
        </div>
        <Badge variant={roster?.live ? "live" : "modeled"}>{roster?.live ? "Live roster" : "Offline seed"}</Badge>
      </div>

      {/* P1 / P2 / blind / complaints / officers cards */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <Kpi label="P1 zones" value={counts.p1} tone="warning" icon={<Flame className="h-5 w-5" />} />
        <Kpi label="P2 zones" value={counts.p2} icon={<Flame className="h-5 w-5" />} />
        <Kpi label="Blind spots" value={counts.blind} icon={<ShieldAlert className="h-5 w-5" />} sub="high-priority · under-observed" />
        <Kpi label="Live complaints" value={openCount} tone={openCount > 0 ? "warning" : "default"} icon={<Megaphone className="h-5 w-5" />} sub="open reports / tickets" />
        <Kpi label="Officers" value={officers.length} tone="primary" icon={<Users className="h-5 w-5" />} />
      </div>

      {/* live troop deployment */}
      <div>
        <h3 className="mb-2 text-sm font-semibold">Live troop deployment</h3>
        <PatrolBoard station={{ slug, name: stationName, lat: center[0], lon: center[1] }} officers={officers} cells={cells} problems={problemsResolved} />
      </div>

      {/* allocation + roster */}
      <div className="grid gap-4 lg:grid-cols-2">
        <AutoAllocatePanel
          slug={slug}
          stationName={stationName}
          cells={cells}
          officers={officers}
          shiftOrder={roster?.shift_order ?? ["A", "B", "C", "D"]}
          shiftLabels={Object.fromEntries(Object.entries(roster?.shifts ?? {}).map(([k, v]) => [k, v.label]))}
        />
        <RosterPanel
          roster={roster}
          loading={loading}
          canManage={canManage}
          onAdd={addOfficer}
          onPatch={patchOfficer}
          onRemove={removeOfficer}
          onSelectOfficer={setPicked}
          selectedOfficerId={picked?.id ?? null}
        />
      </div>

      <OfficerTicketsDialog officer={picked} tickets={tickets} onClose={() => setPicked(null)} />
    </div>
  );
}

// Per-officer view: open / resolved tickets owned by the selected officer. Operational
// ownership tracking only — NOT a performance ranking.
function OfficerTicketsDialog({ officer, tickets, onClose }: { officer: Officer | null; tickets: Ticket[]; onClose: () => void }) {
  const mine = useMemo(() => {
    if (!officer) return [] as Ticket[];
    return tickets.filter((t) => t.assigned_officer === officer.id || (t.assigned_badge && t.assigned_badge === officer.badge));
  }, [officer, tickets]);
  const open = mine.filter((t) => t.status === "open").length;
  const resolved = mine.filter((t) => t.status === "closed" && t.resolution).length;

  return (
    <Dialog open={!!officer} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>
            {officer?.rank} {officer?.name} <span className="num text-sm text-muted-foreground">· {officer?.badge}</span>
          </DialogTitle>
          <DialogDescription>
            Tickets assigned to this officer (operational ownership — never a performance score).
          </DialogDescription>
        </DialogHeader>
        <div className="grid grid-cols-3 gap-2">
          <Mini label="Assigned" value={mine.length} />
          <Mini label="Open" value={open} />
          <Mini label="Resolved" value={resolved} />
        </div>
        <div className="max-h-64 space-y-1.5 overflow-y-auto">
          {mine.length === 0 && <div className="text-sm text-muted-foreground">No tickets assigned to {officer?.badge} yet.</div>}
          {mine.map((t) => (
            <div key={t.id} className="flex items-center justify-between gap-2 rounded-lg border bg-card px-2.5 py-1.5 text-sm">
              <span className="min-w-0 truncate">{t.category ?? t.kind}</span>
              {t.status === "open" ? (
                <Badge variant="warning">Open</Badge>
              ) : t.resolution ? (
                <Badge variant="success">Resolved</Badge>
              ) : (
                <Badge variant="secondary">Closed</Badge>
              )}
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function Mini({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-lg border bg-muted/30 p-2 text-center">
      <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="num text-lg font-bold leading-tight">{value}</div>
    </div>
  );
}
