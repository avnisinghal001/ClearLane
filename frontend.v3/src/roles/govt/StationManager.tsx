import { useCallback, useEffect, useMemo, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { Building2, MapPin, Plus, Trash2, Users } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { DataTable } from "@/components/DataTable";
import { toast } from "@/components/toast";
import { addGovtStation, getGovtStations, removeGovtStation, type GovtStation } from "@/lib/api";
import { num } from "@/lib/format";
import type { Station } from "@/lib/types";

interface ManagedRow {
  slug: string;
  name: string;
  lat: number | null;
  lon: number | null;
  officers: number | null; // from the mutable roster; null = analytics-only
  n_tickets: number;
  n_cells: number;
  open: number;
  mean_pic: number;
  inRoster: boolean; // present in the mutable roster -> removable
}

// Government "Manage stations" panel — a searchable/filterable list (DataTable)
// with per-station counts, open (locate on map) + remove (×) actions, and an
// "Add station" row (name / lat / lon). Reuses GET /api/v3/stations (rich counts)
// and the govt force endpoints (GET/POST/DELETE /api/govt/stations). Auth = govt.
export function StationManager({ analytics, onFocus }: { analytics: Station[]; onFocus: (lat: number, lon: number) => void }) {
  const [roster, setRoster] = useState<GovtStation[] | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [form, setForm] = useState({ name: "", lat: "", lon: "", inspector: "" });
  const [busy, setBusy] = useState(false);
  const [pendingRemove, setPendingRemove] = useState<ManagedRow | null>(null);

  const refresh = useCallback(() => {
    getGovtStations()
      .then((r) => setRoster(r?.stations ?? null))
      .finally(() => setLoaded(true));
  }, []);
  useEffect(() => refresh(), [refresh]);

  // the mutable roster (if reachable as govt) is the source of truth for which
  // stations EXIST + officer counts; enrich it with the rich analytics by slug.
  const canManage = roster !== null;
  const rows = useMemo<ManagedRow[]>(() => {
    const aBy = new Map(analytics.map((s) => [s.slug, s]));
    const rBy = new Map((roster ?? []).map((g) => [g.slug, g]));
    const slugs = new Set<string>([...rBy.keys(), ...aBy.keys()]);
    const out: ManagedRow[] = [];
    for (const slug of slugs) {
      const a = aBy.get(slug);
      const g = rBy.get(slug);
      out.push({
        slug,
        name: g?.name ?? a?.station ?? slug,
        lat: g?.lat ?? a?.lat ?? null,
        lon: g?.lon ?? a?.lon ?? null,
        officers: g ? g.officers : null,
        n_tickets: a?.n_tickets ?? 0,
        n_cells: a?.n_cells ?? 0,
        open: a?.open ?? 0,
        mean_pic: a?.mean_pic ?? 0,
        inRoster: !!g,
      });
    }
    return out.sort((x, y) => y.n_tickets - x.n_tickets);
  }, [analytics, roster]);

  const totalOfficers = useMemo(() => (roster ?? []).reduce((a, g) => a + (g.officers || 0), 0), [roster]);

  async function handleAdd() {
    const name = form.name.trim();
    const lat = parseFloat(form.lat);
    const lon = parseFloat(form.lon);
    if (!name) return toast("Station name required", { tone: "warning" });
    if (Number.isNaN(lat) || Number.isNaN(lon)) return toast("Valid lat/lon required", { tone: "warning" });
    if (lat < 12.8 || lat > 13.29 || lon < 77.44 || lon > 77.77)
      return toast("Coordinate outside Bengaluru", { desc: "lat 12.80–13.29 · lon 77.44–77.77", tone: "warning" });
    setBusy(true);
    const res = await addGovtStation(name, lat, lon, form.inspector.trim());
    setBusy(false);
    if (res.ok) {
      const insp = res.inspector;
      toast("Station added", {
        desc: insp
          ? `${name} · login ${res.slug}/${res.slug} · Inspector ${insp.name} (${insp.badge})`
          : `${name} · login ${res.slug} / ${res.slug}`,
        tone: "success",
      });
      setForm({ name: "", lat: "", lon: "", inspector: "" });
      refresh();
    } else {
      toast("Couldn't add station", { desc: res.error, tone: "warning" });
    }
  }

  async function handleRemove() {
    if (!pendingRemove) return;
    setBusy(true);
    const res = await removeGovtStation(pendingRemove.slug);
    setBusy(false);
    if (res.ok) {
      toast("Station removed", { desc: pendingRemove.name, tone: "info" });
      setPendingRemove(null);
      refresh();
    } else {
      toast("Couldn't remove station", { desc: res.error, tone: "warning" });
    }
  }

  const columns = useMemo<ColumnDef<ManagedRow>[]>(
    () => [
      {
        accessorKey: "name",
        header: "Station",
        cell: ({ row }) => (
          <div className="min-w-0">
            <div className="font-medium">{row.original.name}</div>
            <div className="font-mono text-[11px] text-muted-foreground">{row.original.slug}</div>
          </div>
        ),
      },
      {
        accessorKey: "officers",
        header: "Officers",
        cell: ({ row }) =>
          row.original.officers == null ? (
            <span className="text-muted-foreground">—</span>
          ) : (
            <span className="num inline-flex items-center gap-1">
              <Users className="h-3.5 w-3.5 text-muted-foreground" />
              {row.original.officers}
            </span>
          ),
      },
      { accessorKey: "n_tickets", header: "Tickets", cell: ({ row }) => <span className="num">{num(row.original.n_tickets)}</span> },
      { accessorKey: "n_cells", header: "Cells", cell: ({ row }) => <span className="num">{num(row.original.n_cells)}</span> },
      {
        accessorKey: "open",
        header: "Open",
        cell: ({ row }) => (row.original.open > 0 ? <Badge variant="warning">{row.original.open}</Badge> : <span className="text-muted-foreground">0</span>),
      },
      { accessorKey: "mean_pic", header: "Mean PIC", cell: ({ row }) => <span className="num">{(row.original.mean_pic ?? 0).toFixed(1)}</span> },
      {
        id: "actions",
        header: "",
        cell: ({ row }) => (
          <div className="flex items-center justify-end gap-1">
            <Button
              size="icon"
              variant="ghost"
              title="Locate on map"
              disabled={row.original.lat == null}
              onClick={(e) => {
                e.stopPropagation();
                if (row.original.lat != null && row.original.lon != null) onFocus(row.original.lat, row.original.lon);
              }}
            >
              <MapPin className="h-4 w-4" />
            </Button>
            <Button
              size="icon"
              variant="ghost"
              title={row.original.inRoster ? "Remove station" : "Sign in as Government on the live backend to manage"}
              disabled={!canManage || !row.original.inRoster}
              onClick={(e) => {
                e.stopPropagation();
                setPendingRemove(row.original);
              }}
            >
              <Trash2 className="h-4 w-4 text-destructive" />
            </Button>
          </div>
        ),
      },
    ],
    [canManage, onFocus],
  );

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2 text-base">
            <Building2 className="h-4 w-4 text-primary" /> Manage stations
            <Badge variant="secondary">{rows.length}</Badge>
            {canManage && <Badge variant="secondary">{totalOfficers} officers</Badge>}
          </CardTitle>
          <Badge variant={canManage ? "live" : "modeled"}>{canManage ? "Live · editable" : "Read-only"}</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Add station row (name / lat / lon) */}
        <div className="flex flex-wrap items-end gap-2 rounded-lg border bg-muted/30 p-2.5">
          <div className="flex-1 min-w-[10rem]">
            <label className="mb-1 block text-[11px] font-medium text-muted-foreground">Station name</label>
            <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="e.g. Indiranagar" disabled={!canManage || busy} />
          </div>
          <div className="w-24">
            <label className="mb-1 block text-[11px] font-medium text-muted-foreground">Lat</label>
            <Input value={form.lat} onChange={(e) => setForm({ ...form, lat: e.target.value })} placeholder="12.97" disabled={!canManage || busy} />
          </div>
          <div className="w-24">
            <label className="mb-1 block text-[11px] font-medium text-muted-foreground">Lon</label>
            <Input value={form.lon} onChange={(e) => setForm({ ...form, lon: e.target.value })} placeholder="77.64" disabled={!canManage || busy} />
          </div>
          <div className="min-w-[9rem] flex-1">
            <label className="mb-1 block text-[11px] font-medium text-muted-foreground">
              Inspector <span className="text-muted-foreground/70">(optional)</span>
            </label>
            <Input value={form.inspector} onChange={(e) => setForm({ ...form, inspector: e.target.value })} placeholder="Station House Officer" disabled={!canManage || busy} />
          </div>
          <Button onClick={handleAdd} disabled={!canManage || busy} className="gap-1.5">
            <Plus className="h-4 w-4" /> Add station
          </Button>
        </div>
        {loaded && !canManage && (
          <p className="text-[11px] text-muted-foreground">
            Sign in as <span className="font-medium">Government</span> against the live backend (with MongoDB) to add or remove stations. Showing the read-only
            station list from the analytics artifact.
          </p>
        )}
        {canManage && (
          <p className="text-[11px] text-muted-foreground">
            Adding a station provisions its login (<span className="font-mono">slug / slug</span>) and an <span className="font-medium">Inspector</span> (Station House
            Officer) at the top of the roster, then seeds a supporting force across the four shifts.
          </p>
        )}

        <DataTable
          columns={columns}
          data={rows}
          searchKey="name"
          searchPlaceholder="Search station…"
          initialSort={[{ id: "n_tickets", desc: true }]}
          pageSize={10}
          dense
          empty={loaded ? "No stations." : "Loading stations…"}
        />
        <p className="text-[11px] leading-tight text-muted-foreground">
          Counts (tickets, cells, open, mean PIC) come from <span className="font-mono">/api/v3/stations</span>; add/remove go through the government
          force endpoints. Aggregated to the station level only — never per officer.
        </p>
      </CardContent>

      <Dialog open={!!pendingRemove} onOpenChange={(o) => !o && setPendingRemove(null)}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Remove station?</DialogTitle>
            <DialogDescription>
              This removes <span className="font-medium">{pendingRemove?.name}</span> ({pendingRemove?.slug}) and its officer roster + sessions. Historical
              analytics are unaffected. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPendingRemove(null)} disabled={busy}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={handleRemove} disabled={busy}>
              <Trash2 className="h-4 w-4" /> Remove
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
