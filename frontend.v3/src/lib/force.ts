// Force Command — troop-tracking SIMULATION engine (client-side, deterministic).
//
// HONESTY: officer/unit positions are a deployment SIMULATION for planning and
// demonstration — NEVER a claim about measured traffic or real GPS. It also never
// touches the historical ML scores; it only consumes them as "problems" to cover.
//
// Ported from the v1 frontend/src/lib/force.js to TypeScript for frontend.v3.
// Models patrol units ("Hoysala" teams) per station, grouped by the FOUR rotating
// shifts (mirrors api/clearlane/force.SHIFTS), and auto-allocates idle on-duty
// units to the worst unserved problem zones using a sliding service window so
// coverage visibly rotates over time. Dispatch is LOCAL: units are built only from
// the owning station's roster.
import type { Officer, ShiftDef } from "./types";

export const RANKS = [
  "Inspector",
  "Police Sub-Inspector",
  "Assistant Sub-Inspector",
  "Head Constable",
  "Constable",
];

// FOUR shifts (mirror of the backend FORCE_SHIFTS / ml.v3 config). Each spans 6h;
// "D Night" wraps past midnight. The roster endpoint also returns these so the UI
// is config-driven — this constant is the offline mirror + the sim's duty clock.
export const SHIFTS: Record<string, ShiftDef> = {
  A: { label: "Morning", start: 6, end: 12 },
  B: { label: "Afternoon", start: 12, end: 18 },
  C: { label: "Evening", start: 18, end: 24 },
  D: { label: "Night", start: 0, end: 6 },
};
export const SHIFT_ORDER = ["A", "B", "C", "D"];
export const RANK_ABBR: Record<string, string> = {
  Inspector: "INSP",
  "Police Sub-Inspector": "PSI",
  "Assistant Sub-Inspector": "ASI",
  "Head Constable": "HC",
  Constable: "PC",
};

// Sim-lively timings (demonstration cadence, not realistic minutes).
const SPEED_KMPH = 28;
const SERVICE_MS = 18000; // time a unit spends on-site
const COOLDOWN_MS = 45000; // a served zone is deprioritised this long (window slides)
const VEHICLES = ["Hoysala", "Cheetah", "Pink Hoysala", "Pilot"];

const FIRST = [
  "Arjun", "Vikram", "Suresh", "Ramesh", "Manjunath", "Kiran", "Prakash", "Naveen",
  "Ravi", "Anil", "Deepak", "Girish", "Harish", "Lokesh", "Mahesh", "Praveen",
  "Rakesh", "Santosh", "Umesh", "Nagaraj", "Roopa", "Shilpa",
];
const LAST = [
  "Gowda", "Reddy", "Naik", "Rao", "Shetty", "Kumar", "Murthy", "Hegde", "Patil",
  "Nair", "Babu", "Prasad", "Bhat", "Desai", "Kulkarni",
];

function rng(seed: number) {
  let s = (seed * 2654435761) >>> 0;
  return (n: number) => {
    s = (1103515245 * s + 12345) & 0x7fffffff;
    return s % n;
  };
}
const slugSeed = (slug: string) => [...(slug || "x")].reduce((a, c) => a + c.charCodeAt(0), 0);

export function haversineKm(a: number, b: number, c: number, d: number): number {
  const R = 6371;
  const r = Math.PI / 180;
  const dphi = (c - a) * r;
  const dl = (d - b) * r;
  const x = Math.sin(dphi / 2) ** 2 + Math.cos(a * r) * Math.cos(c * r) * Math.sin(dl / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(x));
}

// Deterministic offline roster (mirrors backend force.py seeding closely enough),
// used only when the live backend roster is unreachable so the demo always renders.
export function genRoster(slug: string, nZones = 12): Officer[] {
  const size = Math.max(8, Math.min(24, Math.round(nZones * 0.4) + 6));
  const nx = rng(slugSeed(slug) + size);
  const plan = ["Inspector"];
  const si = Math.min(2, Math.max(1, Math.floor(size / 6)));
  const asi = Math.min(2, Math.max(1, Math.floor(size / 6)));
  for (let i = 0; i < si; i++) plan.push("Police Sub-Inspector");
  for (let i = 0; i < asi; i++) plan.push("Assistant Sub-Inspector");
  while (plan.length < size) plan.push(nx(10) < 4 ? "Head Constable" : "Constable");
  const prefix = (slug.replace(/[^a-z0-9]/g, "").toUpperCase().slice(0, 3) || "STN").padEnd(3, "X");
  return plan.map((rank, i) => ({
    id: -(slugSeed(slug) * 100 + i) - 1, // negative ids => offline-only (no live PATCH)
    station_slug: slug,
    name: `${FIRST[nx(FIRST.length)]} ${LAST[nx(LAST.length)]}`,
    badge: `${prefix}-${1000 + i}`,
    rank,
    shift: i === 0 ? "A" : SHIFT_ORDER[i % SHIFT_ORDER.length],
    status: "available" as const,
  }));
}

const rankIdx = (r: string) => {
  const i = RANKS.indexOf(r);
  return i < 0 ? 99 : i;
};

export interface Problem {
  id: string;
  name: string;
  lat: number;
  lon: number;
  score: number;
}
export type UnitStatus = "idle" | "enroute" | "on_site" | "returning" | "off_duty";

interface LatLon {
  lat: number;
  lon: number;
}
interface Assignment {
  zoneId: string;
  zoneName: string;
  target: LatLon;
  phase: "enroute" | "on_site" | "returning";
  depart: number;
  eta: number;
  onSiteUntil: number;
  etaKm: number;
}
interface Unit {
  id: string;
  station_slug: string;
  shift: string;
  name: string;
  lead: Officer;
  members: Officer[];
  size: number;
  home: LatLon;
  pos: LatLon;
  status: UnitStatus;
  assignment: Assignment | null;
}
export interface UnitSnapshot {
  id: string;
  name: string;
  shift: string;
  size: number;
  lead: Officer;
  members: Officer[];
  status: UnitStatus;
  lat: number;
  lon: number;
  home: LatLon;
  target: LatLon | null;
  zoneId: string | null;
  zoneName: string | null;
  etaKm: number | null;
}

// Build patrol units from a roster: group each shift's officers into teams of ~3.
export function buildUnits(slug: string, station: LatLon, officers: Officer[]): Unit[] {
  const byShift: Record<string, Officer[]> = {};
  SHIFT_ORDER.forEach((s) => (byShift[s] = []));
  (officers || []).forEach((o) => (byShift[o.shift] || byShift.A).push(o));
  const units: Unit[] = [];
  SHIFT_ORDER.forEach((sh) => {
    const team = byShift[sh].slice().sort((a, b) => rankIdx(a.rank) - rankIdx(b.rank));
    const perUnit = 3;
    const n = Math.max(team.length ? 1 : 0, Math.ceil(team.length / perUnit));
    for (let u = 0; u < n; u++) {
      const members = team.slice(u * perUnit, (u + 1) * perUnit);
      if (!members.length) continue;
      const veh = VEHICLES[(slugSeed(slug) + units.length) % VEHICLES.length];
      units.push({
        id: `${slug}-${sh}-${u}`,
        station_slug: slug,
        shift: sh,
        name: `${veh} ${sh}${u + 1}`,
        lead: members[0],
        members,
        size: members.length,
        home: { lat: station.lat, lon: station.lon },
        pos: { lat: station.lat, lon: station.lon },
        status: "idle",
        assignment: null,
      });
    }
  });
  return units;
}

export function shiftOnDuty(shift: string, hour: number): boolean {
  const s = SHIFTS[shift];
  if (!s) return false;
  return s.start < s.end ? hour >= s.start && hour < s.end : hour >= s.start || hour < s.end;
}

export function shiftForHour(hour: number): string {
  for (const k of SHIFT_ORDER) if (shiftOnDuty(k, hour)) return k;
  return "A";
}
export function shiftLabel(hour: number): string {
  const k = shiftForHour(hour);
  return `${k} · ${SHIFTS[k].label} shift`;
}

// ---- per-station live sim state --------------------------------------------
interface StationState {
  units: Unit[];
  served: Map<string, number>;
  autoAlloc: boolean;
  sig: string; // roster signature -> rebuild units when the roster changes
}
const STATE = new Map<string, StationState>();

function rosterSig(officers: Officer[]): string {
  return officers.map((o) => `${o.id}:${o.shift}:${o.rank}`).join("|");
}

export function ensureStation(slug: string, station: LatLon, officers: Officer[]): StationState {
  const sig = rosterSig(officers);
  const cur = STATE.get(slug);
  if (!cur) {
    STATE.set(slug, { units: buildUnits(slug, station, officers), served: new Map(), autoAlloc: true, sig });
  } else if (cur.sig !== sig || cur.units.length === 0) {
    cur.units = buildUnits(slug, station, officers);
    cur.sig = sig;
  }
  return STATE.get(slug)!;
}
export function setAutoAlloc(slug: string, on: boolean) {
  const s = STATE.get(slug);
  if (s) s.autoAlloc = on;
}
export function getAutoAlloc(slug: string): boolean {
  return STATE.get(slug)?.autoAlloc ?? true;
}

const lerp = (a: number, b: number, t: number) => a + (b - a) * t;

function moveUnit(u: Unit, now: number) {
  const a = u.assignment;
  if (!a) return;
  if (a.phase === "enroute" || a.phase === "returning") {
    const from = a.phase === "enroute" ? u.home : a.target;
    const to = a.phase === "enroute" ? a.target : u.home;
    const t = a.eta > a.depart ? Math.min(1, (now - a.depart) / (a.eta - a.depart)) : 1;
    u.pos = { lat: lerp(from.lat, to.lat, t), lon: lerp(from.lon, to.lon, t) };
    if (t >= 1) {
      if (a.phase === "enroute") {
        a.phase = "on_site";
        a.onSiteUntil = now + SERVICE_MS;
        u.status = "on_site";
      } else {
        u.assignment = null;
        u.status = "idle";
        u.pos = { ...u.home };
      }
    }
  } else if (a.phase === "on_site") {
    if (now >= a.onSiteUntil) {
      STATE.get(u.station_slug)?.served.set(a.zoneId, now);
      const dKm = haversineKm(u.pos.lat, u.pos.lon, u.home.lat, u.home.lon);
      a.phase = "returning";
      a.depart = now;
      a.eta = now + (dKm / SPEED_KMPH) * 3600 * 1000;
      u.status = "returning";
    }
  }
}

function assign(u: Unit, prob: Problem, now: number) {
  const dKm = haversineKm(u.home.lat, u.home.lon, prob.lat, prob.lon);
  u.assignment = {
    zoneId: prob.id,
    zoneName: prob.name,
    target: { lat: prob.lat, lon: prob.lon },
    phase: "enroute",
    depart: now,
    eta: now + (dKm / SPEED_KMPH) * 3600 * 1000,
    onSiteUntil: 0,
    etaKm: dKm,
  };
  u.status = "enroute";
}

export interface TickCtx {
  now?: number;
  hour: number;
  problems?: Problem[];
}

// Advance the sim one step and return the unit snapshots.
export function tick(slug: string, station: LatLon, officers: Officer[], ctx: TickCtx): UnitSnapshot[] {
  const s = ensureStation(slug, station, officers);
  const now = ctx.now || Date.now();
  s.units.forEach((u) => {
    const duty = shiftOnDuty(u.shift, ctx.hour);
    if (!duty) {
      u.status = "off_duty";
      u.assignment = null;
      u.pos = { ...u.home };
    } else if (u.status === "off_duty") {
      u.status = "idle";
    }
  });
  s.units.forEach((u) => {
    if (u.status !== "off_duty") moveUnit(u, now);
  });
  if (s.autoAlloc) autoAllocate(slug, ctx.problems || [], now);
  return snapshotUnits(slug);
}

// Sliding-window allocator: idle on-duty units take the worst unserved problem (one
// not currently targeted and not recently served). As units finish and zones cool
// down, the assignment window "slides" down the ranked problem list.
export function autoAllocate(slug: string, problems: Problem[], now = Date.now()) {
  const s = STATE.get(slug);
  if (!s) return [];
  const targeted = new Set(s.units.map((u) => u.assignment?.zoneId).filter(Boolean));
  const idle = s.units.filter((u) => u.status === "idle");
  const ranked = problems.slice().sort((a, b) => b.score - a.score);
  const plan: { unit: string; zone: string; etaKm: number }[] = [];
  for (const u of idle) {
    const prob = ranked.find((p) => !targeted.has(p.id) && now - (s.served.get(p.id) || 0) > COOLDOWN_MS);
    if (!prob) break;
    assign(u, prob, now);
    targeted.add(prob.id);
    plan.push({ unit: u.name, zone: prob.name, etaKm: u.assignment!.etaKm });
  }
  return plan;
}

// Manual dispatch: send a named unit to a specific problem zone (manual override).
export function dispatchUnit(slug: string, unitId: string, prob: Problem): Unit | null {
  const s = STATE.get(slug);
  if (!s) return null;
  const u = s.units.find((x) => x.id === unitId);
  if (!u || u.status === "off_duty") return null;
  assign(u, prob, Date.now());
  return u;
}

export function snapshotUnits(slug: string): UnitSnapshot[] {
  const s = STATE.get(slug);
  if (!s) return [];
  return s.units.map((u) => ({
    id: u.id,
    name: u.name,
    shift: u.shift,
    size: u.size,
    lead: u.lead,
    members: u.members,
    status: u.status,
    lat: u.pos.lat,
    lon: u.pos.lon,
    home: u.home,
    target: u.assignment ? u.assignment.target : null,
    zoneId: u.assignment?.zoneId || null,
    zoneName: u.assignment?.zoneName || null,
    etaKm: u.assignment?.etaKm || null,
  }));
}

export interface ForceCounts {
  units_total: number;
  on_duty: number;
  enroute: number;
  on_site: number;
  idle: number;
  officers_on_duty: number;
}

export function forceCounts(slug: string): ForceCounts {
  const u = snapshotUnits(slug);
  const onDuty = u.filter((x) => x.status !== "off_duty");
  return {
    units_total: u.length,
    on_duty: onDuty.length,
    enroute: u.filter((x) => x.status === "enroute").length,
    on_site: u.filter((x) => x.status === "on_site" || x.status === "returning").length,
    idle: u.filter((x) => x.status === "idle").length,
    officers_on_duty: onDuty.reduce((a, x) => a + x.size, 0),
  };
}

// Light/orange-theme status palette (green ready -> orange on-site).
export const STATUS_COLOR: Record<UnitStatus, string> = {
  idle: "#16a34a",
  enroute: "#2563eb",
  on_site: "#ea580c",
  returning: "#9333ea",
  off_duty: "#94a3b8",
};
export const STATUS_LABEL: Record<UnitStatus, string> = {
  idle: "ready",
  enroute: "en route",
  on_site: "on site",
  returning: "returning",
  off_duty: "off duty",
};
