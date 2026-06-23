import { useEffect, useMemo, useRef, useState } from "react";
import { Radio, Crosshair } from "lucide-react";
import { ClearLaneMap, type MapPin } from "@/components/map/ClearLaneMap";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import {
  type ForceCounts,
  type Problem,
  type UnitSnapshot,
  STATUS_COLOR,
  STATUS_LABEL,
  dispatchUnit,
  forceCounts,
  getAutoAlloc,
  setAutoAlloc,
  shiftForHour,
  shiftLabel,
  snapshotUnits,
  tick,
} from "@/lib/force";
import type { Cell, Officer } from "@/lib/types";

function istHour(): number {
  const d = new Date();
  const ist = new Date(d.getTime() + (330 + d.getTimezoneOffset()) * 60000);
  return ist.getHours();
}

interface StationLite {
  slug: string;
  name: string;
  lat: number;
  lon: number;
}

// Live troop-deployment board. Runs the client-side patrol SIMULATION (force.ts)
// over the existing MapMyIndia map engine: troop markers (coloured by status) +
// a Station HQ marker over the station's priority zones, a Shift-clock slider that
// scrubs the active shift, and an Auto-allocate (sliding-window) toggle. Dispatch
// is LOCAL — units are built only from this station's roster.
// HONESTY: positions are a SIMULATION for planning, never real GPS.
export function PatrolBoard({
  station,
  officers,
  cells,
  problems,
  focusCell,
}: {
  station: StationLite;
  officers: Officer[];
  cells: Cell[];
  problems: Problem[];
  focusCell?: Cell | null;
}) {
  const slug = station.slug;
  const [units, setUnits] = useState<UnitSnapshot[]>([]);
  const [hour, setHour] = useState(istHour());
  const [auto, setAuto] = useState(getAutoAlloc(slug));
  const [flyTo, setFlyTo] = useState<[number, number] | null>(null);

  const problemsRef = useRef(problems);
  problemsRef.current = problems;
  const hourRef = useRef(hour);
  hourRef.current = hour;
  const officersRef = useRef(officers);
  officersRef.current = officers;

  useEffect(() => setAutoAlloc(slug, auto), [slug, auto]);

  useEffect(() => {
    if (focusCell) setFlyTo([focusCell.lat, focusCell.lon]);
  }, [focusCell]);

  // run the sim loop (deterministic, 500ms cadence) — re-armed when the station changes
  useEffect(() => {
    setFlyTo([station.lat, station.lon]);
    const run = () =>
      setUnits(tick(slug, { lat: station.lat, lon: station.lon }, officersRef.current, { now: Date.now(), hour: hourRef.current, problems: problemsRef.current }));
    run();
    const t = setInterval(run, 500);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug, station.lat, station.lon]);

  const counts: ForceCounts = useMemo(() => forceCounts(slug), [units, slug]);
  const activeShift = shiftForHour(hour);

  const pins = useMemo<MapPin[]>(() => {
    const out: MapPin[] = [
      { key: `hq-${slug}`, lat: station.lat, lon: station.lon, color: "#0f172a", label: `${station.name} HQ` },
    ];
    for (const u of units) {
      const onDuty = u.status !== "off_duty";
      out.push({
        key: u.id,
        lat: u.lat,
        lon: u.lon,
        color: STATUS_COLOR[u.status],
        pulse: u.status === "enroute",
        label: `${u.name} · shift ${u.shift} · ${STATUS_LABEL[u.status]}${u.zoneName ? ` → ${u.zoneName}` : ""} · lead ${u.lead?.rank} ${u.lead?.name}${onDuty ? "" : " (off duty)"}`,
      });
    }
    if (focusCell) {
      out.push({
        key: `focus-${focusCell.h3_r10}`,
        lat: focusCell.lat,
        lon: focusCell.lon,
        color: "#38bdf8",
        pulse: true,
        label: `${focusCell.police_station ?? station.name} · selected dispatch zone`,
      });
    }
    return out;
  }, [units, slug, station.lat, station.lon, station.name, focusCell]);

  // manual override: send the next idle on-duty unit to the worst unserved zone
  function dispatchWorst() {
    const idle = units.find((u) => u.status === "idle");
    if (idle && problems[0]) {
      dispatchUnit(slug, idle.id, problems[0]);
      setUnits(snapshotUnits(slug)); // reflect immediately, before the next tick
    }
  }

  const onDutyUnits = units.filter((u) => u.status !== "off_duty");

  return (
    <div className="space-y-3">
      <div className="relative h-[56vh] min-h-[360px] w-full overflow-hidden rounded-xl border">
        <ClearLaneMap cells={cells} source="live" flyTo={flyTo} pins={pins} defaultZoom={13} sizeMode="pressure" />

        {/* shift clock + auto-allocate control card (top-left overlay) */}
        <div className="absolute left-2 top-2 z-[500] w-[min(19rem,calc(100%-4.5rem))] space-y-2 rounded-xl border bg-background/95 p-3 shadow-lg backdrop-blur">
          <label className="flex cursor-pointer items-center justify-between gap-2">
            <span className="flex items-center gap-1.5 text-[13px] font-medium">
              <Radio className="h-4 w-4 text-primary" /> Auto-allocate
              <span className="text-[10px] font-normal text-muted-foreground">(sliding window)</span>
            </span>
            <Switch checked={auto} onCheckedChange={setAuto} />
          </label>
          <div>
            <div className="flex items-center justify-between">
              <span className="text-[11px] text-muted-foreground">Shift clock</span>
              <span className="flex items-center gap-1.5">
                <b className="num text-sm">{String(hour).padStart(2, "0")}:00</b>
                <span className="rounded-full border border-primary px-1.5 py-0.5 text-[10px] font-semibold text-primary">{shiftLabel(hour)}</span>
              </span>
            </div>
            <input type="range" min={0} max={23} value={hour} onChange={(e) => setHour(+e.target.value)} className="mt-1 w-full accent-primary" aria-label="Shift clock hour" />
          </div>
          {!auto && (
            <Button size="sm" variant="outline" className="w-full gap-1.5" onClick={dispatchWorst} disabled={!onDutyUnits.some((u) => u.status === "idle") || !problems.length}>
              <Crosshair className="h-3.5 w-3.5" /> Dispatch idle → worst zone
            </Button>
          )}
        </div>
      </div>

      {/* live status board — units on duty: ready / en route / on site */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatBox label="Units on duty" value={`${counts.on_duty}/${counts.units_total}`} sub={`${counts.officers_on_duty} officers · shift ${activeShift}`} />
        <StatBox label="Ready" value={counts.idle} dot={STATUS_COLOR.idle} />
        <StatBox label="En route" value={counts.enroute} dot={STATUS_COLOR.enroute} />
        <StatBox label="On site" value={counts.on_site} dot={STATUS_COLOR.on_site} />
      </div>

      {/* on-duty unit roster strip */}
      {onDutyUnits.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {onDutyUnits.map((u) => (
            <span key={u.id} className="inline-flex items-center gap-1.5 rounded-full border bg-card px-2 py-1 text-[11px]">
              <span className="h-2 w-2 rounded-full" style={{ background: STATUS_COLOR[u.status] }} />
              <span className="font-medium">{u.name}</span>
              <span className="text-muted-foreground">{STATUS_LABEL[u.status]}{u.zoneName ? ` → ${u.zoneName}` : ""}</span>
            </span>
          ))}
        </div>
      )}

      <p className="text-[11px] leading-tight text-muted-foreground">
        Patrol deployment for planning — positions are <b>not real GPS</b>. Auto-allocate sends idle on-duty units to the worst unserved
        zones; after a service window each zone cools down so coverage <b>slides</b> down the queue. Units are drawn only from this station's roster
        (local dispatch). Zones are MODELED priority — never measured congestion.
      </p>
    </div>
  );
}

function StatBox({ label, value, sub, dot }: { label: string; value: React.ReactNode; sub?: string; dot?: string }) {
  return (
    <div className="rounded-xl border bg-card p-3">
      <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        {dot && <span className="h-2 w-2 rounded-full" style={{ background: dot }} />}
        {label}
      </div>
      <div className="num mt-1 text-2xl font-bold leading-none">{value}</div>
      {sub && <div className="mt-1 text-[11px] text-muted-foreground">{sub}</div>}
    </div>
  );
}
