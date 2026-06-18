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

// min distance (km) from a point to a polyline path ([[lat,lon], ...])
function pointToPathKm(p, path) {
  let min = Infinity;
  for (let i = 1; i < path.length; i++) {
    const d = segDistKm(p, { lat: path[i - 1][0], lon: path[i - 1][1] },
      { lat: path[i][0], lon: path[i][1] });
    if (d < min) min = d;
  }
  return min;
}

// Score a road route (polyline) by the parking-obstruction risk of nearby zones.
export function scoreRoute(path, zones, maxKm = 0.45) {
  if (!path || path.length < 2) return { risk: 0, worst: [], near: [] };
  const near = zones.filter((z) => z.lat != null && pointToPathKm(z, path) <= maxKm);
  if (!near.length) return { risk: 0, worst: [], near: [] };
  const worst = [...near].sort((a, b) => (b.pressure || 0) - (a.pressure || 0));
  const top = worst.slice(0, Math.min(5, worst.length));
  const risk = Math.round(top.reduce((s, z) => s + (z.pressure || 0), 0) / top.length);
  return { risk, worst: worst.slice(0, 6), near };
}

// equirectangular helpers for the avoidance geometry
function km2ll(x, y, lat0) {
  const R = 6371, r = Math.PI / 180;
  return { lat: y / (R * r), lon: x / (R * r * Math.cos(lat0 * r)) };
}

// A waypoint that pulls the route to the FAR side of the worst-obstruction cluster.
function avoidanceWaypoint(from, to, hotspots) {
  if (!hotspots.length) return null;
  let wlat = 0, wlon = 0, ws = 0;
  for (const z of hotspots) { const w = z.pressure || 1; wlat += z.lat * w; wlon += z.lon * w; ws += w; }
  const H = { lat: wlat / ws, lon: wlon / ws };
  const lat0 = (from.lat + to.lat) / 2;
  const A = ll2km(from.lat, from.lon, lat0), B = ll2km(to.lat, to.lon, lat0), Hk = ll2km(H.lat, H.lon, lat0);
  const dx = B[0] - A[0], dy = B[1] - A[1], len = Math.hypot(dx, dy) || 1e-9;
  const ux = dx / len, uy = dy / len;
  const t = (Hk[0] - A[0]) * ux + (Hk[1] - A[1]) * uy;
  const proj = [A[0] + t * ux, A[1] + t * uy];
  let px = Hk[0] - proj[0], py = Hk[1] - proj[1];
  const pd = Math.hypot(px, py) || 1e-9;
  const offset = pd + 1.3;                       // push to the far side of the cluster
  const W = [proj[0] - (px / pd) * offset, proj[1] - (py / pd) * offset];
  return km2ll(W[0], W[1], lat0);
}

async function osrmRoute(stops) {
  const path = stops.map((c) => `${c.lon},${c.lat}`).join(";");
  const r = await fetch(`https://router.project-osrm.org/route/v1/driving/${path}` +
    `?overview=full&geometries=geojson&alternatives=${stops.length === 2}`);
  if (!r.ok) throw new Error("osrm");
  const j = await r.json();
  if (!j.routes?.length) throw new Error("no routes");
  return j.routes;
}
const toCoords = (rt) => rt.geometry.coordinates.map(([lon, lat]) => [lat, lon]);

// Fetch road routes from OSRM (free, no key), rank by obstruction risk, and add a
// dedicated route that DETOURS around the worst hotspots. Offline → straight line.
export async function fetchRankedRoutes(from, to, zones) {
  try {
    const raw = await osrmRoute([from, to]);          // direct + alternatives
    const routes = raw.map((rt) => {
      const coords = toCoords(rt);
      const sc = scoreRoute(coords, zones);
      return { coords, ...sc, level: obsLevel(sc.risk),
        km: +(rt.distance / 1000).toFixed(1), min: Math.round(rt.duration / 60), avoids: false };
    });
    routes.sort((a, b) => a.risk - b.risk);

    // build an explicit "avoids hotspots" detour around the worst spots
    const hot = (routes[0]?.worst || []).filter((z) => (z.pressure || 0) >= 50);
    const wp = avoidanceWaypoint(from, to, hot);
    if (wp) {
      try {
        const av = (await osrmRoute([from, wp, to]))[0];
        const coords = toCoords(av);
        const sc = scoreRoute(coords, zones);
        const base = routes[0];
        const longer = av.distance / 1000 <= (base.km || 999) * 1.7;
        const cleaner = sc.risk <= base.risk - 3;
        // only offer it if it genuinely lowers obstruction without a huge detour
        if (cleaner && longer) {
          routes.push({ coords, ...sc, level: obsLevel(sc.risk),
            km: +(av.distance / 1000).toFixed(1), min: Math.round(av.duration / 60), avoids: true });
        }
      } catch { /* keep the normal routes */ }
    }
    routes.sort((a, b) => a.risk - b.risk);
    return routes.slice(0, 4);
  } catch {
    const coords = [[from.lat, from.lon], [to.lat, to.lon]];
    const sc = scoreRoute(coords, zones, 0.9);
    return [{ coords, ...sc, level: obsLevel(sc.risk), km: null, min: null, straight: true, avoids: false }];
  }
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
