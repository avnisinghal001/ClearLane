// Offline mirror of the /api/v3 write loop (complaints + tickets), used when the
// backend is unreachable so the demo always works. Mirrors the honesty contract's
// three-number separation: historical pic_score is immutable; a transparent,
// decaying live_adjustment rides on top; operational_priority = clamp(sum, 0..100).
import type { Cell, ComplaintInput, ResolveInput, Ticket, TicketInput } from "./types";

const COMPLAINT_BOOST = 12; // each verified-intent complaint nudges the cell
const MAX_ADJUSTMENT = 40; // cap (matches backend OP_RULES intent)
const DECAY_PER_HOUR = 3; // live adjustment relaxes toward 0

interface Boost {
  boost: number;
  ts: number;
}

let _cells: Cell[] = [];
let _tickets: Ticket[] = [];
const _adj = new Map<string, Boost>();
let _seeded = false;
let _seq = 1;

export function seed(cells: Cell[], tickets: Ticket[]) {
  _cells = cells;
  if (!_seeded) {
    _tickets = tickets.map((t) => ({ ...t }));
    _seeded = true;
  }
}

function haversineKm(aLat: number, aLon: number, bLat: number, bLon: number): number {
  const R = 6371;
  const dLat = ((bLat - aLat) * Math.PI) / 180;
  const dLon = ((bLon - aLon) * Math.PI) / 180;
  const s =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((aLat * Math.PI) / 180) * Math.cos((bLat * Math.PI) / 180) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(s));
}

export function nearestCell(lat: number, lon: number): Cell | null {
  let best: Cell | null = null;
  let bestD = Infinity;
  for (const c of _cells) {
    const d = haversineKm(lat, lon, c.lat, c.lon);
    if (d < bestD) {
      bestD = d;
      best = c;
    }
  }
  return best;
}

export function liveAdjustment(h3: string | null | undefined): number {
  if (!h3) return 0;
  const b = _adj.get(h3);
  if (!b) return 0;
  const hours = (Date.now() - b.ts) / 3600000;
  return Math.max(0, Math.min(MAX_ADJUSTMENT, b.boost - DECAY_PER_HOUR * hours));
}

function bump(h3: string, amount: number) {
  const cur = liveAdjustment(h3);
  _adj.set(h3, { boost: Math.min(MAX_ADJUSTMENT, cur + amount), ts: Date.now() });
}

export function listTickets(): Ticket[] {
  return _tickets.slice().sort((a, b) => +new Date(b.created_at) - +new Date(a.created_at));
}

export function postComplaint(input: ComplaintInput): Ticket {
  const cell = nearestCell(input.lat, input.lon);
  if (cell) bump(cell.h3_r10, COMPLAINT_BOOST);
  const t: Ticket = {
    id: `CMP-${Date.now().toString(36)}-${_seq++}`,
    kind: "citizen_complaint",
    category: input.category,
    labels: [input.category],
    station: cell?.police_station ?? null,
    cell: cell?.h3_r10 ?? null,
    lat: input.lat,
    lon: input.lon,
    vehicle_type: input.vehicle_type ?? null,
    vehicle_number: input.vehicle_number ?? null,
    note: input.description || null,
    traffic_caused: input.traffic_caused,
    status: "open",
    resolution: null,
    reason: null,
    reason_other: null,
    created_at: new Date().toISOString(),
    source: "offline",
  };
  _tickets.unshift(t);
  return t;
}

export function postTicket(input: TicketInput): Ticket {
  const t: Ticket = {
    id: `TKT-${Date.now().toString(36)}-${_seq++}`,
    kind: input.kind,
    category: input.category,
    labels: input.labels?.length ? input.labels : input.category ? [input.category] : [],
    station: input.station ?? null,
    cell: input.cell ?? null,
    lat: input.lat ?? null,
    lon: input.lon ?? null,
    vehicle_type: input.vehicle_type ?? null,
    vehicle_number: input.vehicle_number ?? null,
    note: input.note ?? null,
    traffic_caused: null,
    status: "open",
    resolution: null,
    reason: null,
    reason_other: null,
    created_at: new Date().toISOString(),
    source: "offline",
  };
  _tickets.unshift(t);
  return t;
}

export function patchTicket(id: string, body: ResolveInput): Ticket | null {
  const t = _tickets.find((x) => x.id === id);
  if (!t) return null;
  t.status = body.status;
  t.resolution = body.resolution;
  t.reason = body.reason;
  t.reason_other = body.reason_other ?? null;
  // A "cleared/false alarm" resolution relaxes the cell's live adjustment.
  if (t.cell) _adj.set(t.cell, { boost: 0, ts: Date.now() });
  return t;
}
