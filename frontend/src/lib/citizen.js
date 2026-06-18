// Citizen-side helpers. HONESTY: "obstruction risk" is derived from parking-
// violation patterns (enforcement data), NOT live traffic sensors. We say so in
// the UI. Patrol counts reuse the same deployment simulation as the police side.
import { genRoster, buildUnits, shiftOnDuty } from "./force.js";

export function obsLevel(v) {
  if (v == null) return { key: "unknown", label: "No data", color: "#5b6472", pct: 0 };
  if (v >= 66) return { key: "heavy", label: "Heavy obstruction risk", color: "#E24B4A", pct: v };
  if (v >= 33) return { key: "moderate", label: "Some obstruction", color: "#EF9F27", pct: v };
  return { key: "clear", label: "Likely clear", color: "#6FE3A6", pct: v };
}

export function istHour() {
  const d = new Date();
  const ist = new Date(d.getTime() + (330 + d.getTimezoneOffset()) * 60000);
  return ist.getHours();
}

// Patrol units / officers on duty NOW for a station (same sim as the police side).
export function patrolsOnDuty(slug, st, hour = istHour()) {
  try {
    const roster = genRoster(slug, st?.n_zones || 12);
    const units = buildUnits(slug, { lat: st?.lat, lon: st?.lon, name: st?.station || slug }, roster);
    const onDuty = units.filter((u) => shiftOnDuty(u.shift, hour));
    return { units: onDuty.length, officers: onDuty.reduce((a, u) => a + u.size, 0), total: units.length };
  } catch { return { units: 0, officers: 0, total: 0 }; }
}

// equirectangular projection to km around a reference latitude
function ll2km(lat, lon, lat0) {
  const R = 6371, r = Math.PI / 180;
  return [R * lon * r * Math.cos(lat0 * r), R * lat * r];
}
function segDistKm(p, a, b) {
  const lat0 = (a.lat + b.lat) / 2;
  const P = ll2km(p.lat, p.lon, lat0), A = ll2km(a.lat, a.lon, lat0), B = ll2km(b.lat, b.lon, lat0);
  const dx = B[0] - A[0], dy = B[1] - A[1];
  const len2 = dx * dx + dy * dy || 1e-9;
  let t = ((P[0] - A[0]) * dx + (P[1] - A[1]) * dy) / len2;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(P[0] - (A[0] + t * dx), P[1] - (A[1] + t * dy));
}

export function corridorZones(from, to, zones, maxKm = 0.9) {
  if (!from || !to) return [];
  return zones.filter((z) => z.lat != null && segDistKm(z, from, to) <= maxKm);
}

// Route advisory between two points, from parking-obstruction data.
export function routeAdvisory(from, to, zones) {
  const corr = corridorZones(from, to, zones);
  if (!corr.length) return { corridor: [], risk: 0, worst: [], level: obsLevel(0) };
  const worst = [...corr].sort((a, b) => (b.pressure || 0) - (a.pressure || 0));
  const top = worst.slice(0, Math.min(5, worst.length));
  const risk = Math.round(top.reduce((s, z) => s + (z.pressure || 0), 0) / top.length);
  return { corridor: corr, risk, worst: worst.slice(0, 5), level: obsLevel(risk) };
}
