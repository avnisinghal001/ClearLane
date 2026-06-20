import { useEffect, useMemo, useRef, useState } from "react";
import { MapContainer, TileLayer, CircleMarker, Polyline, Tooltip, useMap, useMapEvents } from "react-leaflet";
import { api, opSnapshot, opComplaint, seedOpZones } from "../lib/api.js";
import { mapsUrl } from "../lib/format.js";
import { slugify } from "../lib/auth.js";
import { Icon } from "./icons.jsx";
import { obsLevel, patrolsOnDuty, fetchRankedRoutes, istHour } from "../lib/citizen.js";
import { istToday, activityField, fmtDate } from "../lib/timeLens.js";

const CENTER = [12.9716, 77.5946];
const DARK = "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png";
const ROUTE_BLUE = "#3AA0FF";
const HELPLINE = "103"; // Bengaluru Traffic Police helpline
const VEHICLES = ["CAR", "SCOOTER", "MOTOR CYCLE", "PASSENGER AUTO", "LGV", "PRIVATE BUS", "GOODS AUTO"];

function FlyTo({ pos }) {
  const map = useMap();
  useEffect(() => { if (pos) map.flyTo(pos, 16, { duration: 0.7 }); }, [pos]);
  return null;
}
function ClickCatcher({ active, onPick }) {
  useMapEvents({ click(e) { if (active) onPick([e.latlng.lat, e.latlng.lng]); } });
  return null;
}
function FitRoute({ coords }) {
  const map = useMap();
  useEffect(() => {
    if (coords?.length > 1) map.fitBounds(coords, { padding: [50, 50], maxZoom: 15 });
  }, [coords]);
  return null;
}

export default function CitizenApp() {
  const [zones, setZones] = useState([]);
  const [daily, setDaily] = useState(null);
  const [stationMeta, setStationMeta] = useState({});
  const [snapshot, setSnapshot] = useState(null);
  const [tab, setTab] = useState("map");          // map | trip | report
  const [selected, setSelected] = useState(null); // selected zone
  const [flyTo, setFlyTo] = useState(null);
  const [pending, setPending] = useState(null);   // [lat,lon] awaiting report
  const [form, setForm] = useState({ description: "", vehicle_type: "CAR" });
  const [toast, setToast] = useState(null);
  const [trip, setTrip] = useState({ from: null, to: null });
  const [routes, setRoutes] = useState([]);
  const [routeSel, setRouteSel] = useState(0);
  const [routeLoading, setRouteLoading] = useState(false);
  const hour = istHour();

  useEffect(() => {
    api("/api/map/payload").then((p) => { setZones(p.zones || []); seedOpZones(p.zones || []); }).catch(() => {});
    api("/api/daily").then(setDaily).catch(() => {});
    api("/api/stations").then((list) => {
      const m = {}; (list || []).forEach((s) => { m[s.station] = s; }); setStationMeta(m);
    }).catch(() => {});
    const sync = () => opSnapshot().then(setSnapshot).catch(() => {});
    sync();
    const t = setInterval(sync, 6000);
    return () => clearInterval(t);
  }, []);

  const complaints = (snapshot?.complaints || []).filter((c) => c.status !== "resolved");
  const reportMode = tab === "report";

  // TODAY's predicted obstruction: project each zone onto today's weekday × hour
  // pattern, normalised 0..100. Falls back to structural pressure if unavailable.
  const today = istToday();
  const todayName = fmtDate(today);
  const zonesT = useMemo(() => {
    const field = activityField(zones, { mode: "date", date: today, hour: null }, daily);
    const useToday = field.max > 0;
    return zones.map((z) => ({
      ...z,
      pressure: useToday ? Math.round((field.vals[z.id] / field.max) * 100) : (z.pressure || 0),
      _allTime: z.pressure,
    }));
  }, [zones, daily, today]);

  // keep the selected zone in sync with today's recomputed values
  const selZone = selected ? (zonesT.find((z) => z.id === selected.id) || selected) : null;
  const stationFor = (z) => z && stationMeta[z.station];
  const patrol = useMemo(() => {
    const z = selZone; const st = stationFor(z);
    if (!z || !st) return null;
    return { name: z.station, ...patrolsOnDuty(slugify(z.station), st, hour) };
  }, [selZone, stationMeta, hour]);

  // compute ranked road routes (scored on TODAY's predicted obstruction)
  useEffect(() => {
    if (!(trip.from && trip.to) || !zonesT.length) { setRoutes([]); return; }
    let alive = true;
    setRouteLoading(true);
    fetchRankedRoutes(trip.from, trip.to, zonesT).then((rs) => {
      if (!alive) return;
      setRoutes(rs); setRouteSel(0); setRouteLoading(false);
    });
    return () => { alive = false; };
  }, [trip, zonesT]);
  const sel = routes[routeSel] || null;

  function pickZone(z) { setSelected(z); setTab("map"); setFlyTo([z.lat, z.lon]); }

  async function submitReport() {
    try {
      const r = await opComplaint({ lat: pending[0], lon: pending[1], ...form });
      setToast(`Thanks — reported near ${r.zone_name || "your spot"}${r.station ? ` · ${r.station} police notified` : ""}.`);
    } catch (e) { setToast(`Couldn't file: ${e.message}`); }
    setPending(null); setForm({ description: "", vehicle_type: "CAR" });
    setTimeout(() => setToast(null), 4500);
  }

  function useMyLocation(which) {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition((p) => {
      const pt = { lat: p.coords.latitude, lon: p.coords.longitude, name: "My location" };
      setTrip((t) => ({ ...t, [which]: pt }));
    });
  }

  return (
    <div className="citizen">
      <header className="citizen-head">
        <div className="wordmark">
          <span className="brand-mark hdr-mark"><Icon name="lane" size={28} strokeWidth={2} /></span>
          Clear<span className="lane">Lane</span> <span className="citizen-tag">Citizen</span>
        </div>
        <div className="spacer" />
        <a className="btn" href="#/" onClick={() => { window.location.hash = "#/"; }}>
          <Icon name="shield" size={14} /> Authority login</a>
      </header>

      <div className="citizen-map">
        <MapContainer center={CENTER} zoom={12} preferCanvas style={{ height: "100%" }}>
          <TileLayer url={DARK} attribution="© OpenStreetMap, © CARTO" />
          <FlyTo pos={flyTo} />
          <ClickCatcher active={reportMode} onPick={setPending} />

          {/* TODAY's predicted obstruction-risk zones */}
          {zonesT.map((z) => {
            const lv = obsLevel(z.pressure);
            const isSel = selected?.id === z.id;
            return (
              <CircleMarker key={z.id} center={[z.lat, z.lon]}
                radius={4 + (z.pressure / 100) * 13}
                pathOptions={{ color: isSel ? "#fff" : lv.color, weight: isSel ? 2 : 1,
                  fillColor: lv.color, fillOpacity: 0.5 }}
                eventHandlers={{ click: () => pickZone(z) }}>
                <Tooltip>{z.name} — {lv.label} today</Tooltip>
              </CircleMarker>
            );
          })}

          {/* alternate routes (dimmed) */}
          {routes.map((rt, i) => i === routeSel ? null : (
            <Polyline key={"alt" + i} positions={rt.coords}
              pathOptions={{ color: "#7b879b", weight: 3, opacity: 0.45, dashArray: rt.straight ? "8" : "1 8", lineCap: "round" }}
              eventHandlers={{ click: () => setRouteSel(i) }} />
          ))}
          {/* selected route — blue glowing line */}
          {sel && <>
            <Polyline positions={sel.coords}
              pathOptions={{ color: ROUTE_BLUE, weight: 16, opacity: 0.18, lineCap: "round" }} />
            <Polyline positions={sel.coords} className="route-glow"
              pathOptions={{ color: ROUTE_BLUE, weight: 6, opacity: 1, lineCap: "round",
                dashArray: sel.straight ? "10" : null }} />
            <FitRoute coords={sel.coords} />
          </>}
          {/* worst spots on the chosen route */}
          {sel?.worst?.map((z) => (
            <CircleMarker key={"w" + z.id} center={[z.lat, z.lon]} radius={9}
              pathOptions={{ color: "#EF9F27", weight: 2, fill: false, dashArray: "4" }}
              eventHandlers={{ click: () => pickZone(z) }}>
              <Tooltip>{z.name} — watch out</Tooltip>
            </CircleMarker>
          ))}
          {/* trip endpoints */}
          {trip.from && <CircleMarker center={[trip.from.lat, trip.from.lon]} radius={8}
            pathOptions={{ color: "#0b0e14", weight: 3, fillColor: "#6FE3A6", fillOpacity: 1 }}>
            <Tooltip permanent direction="top">Start</Tooltip></CircleMarker>}
          {trip.to && <CircleMarker center={[trip.to.lat, trip.to.lon]} radius={8}
            pathOptions={{ color: "#0b0e14", weight: 3, fillColor: "#E24B4A", fillOpacity: 1 }}>
            <Tooltip permanent direction="top">End</Tooltip></CircleMarker>}

          {/* live citizen reports */}
          {complaints.map((c) => (
            <CircleMarker key={"c" + c.id} center={[c.lat, c.lon]} radius={6}
              pathOptions={{ color: "#4aa3ff", weight: 2, fillColor: "#4aa3ff", fillOpacity: 0.6, className: "op-pulse" }}>
              <Tooltip>Reported: {c.vehicle_type || "obstruction"}</Tooltip>
            </CircleMarker>
          ))}
        </MapContainer>

        {/* legend chip */}
        <div className="citizen-legend">
          <span className="citizen-legend-title"><Icon name="today" size={12} /> Today</span>
          <span><i style={{ background: "#6FE3A6" }} /> clear</span>
          <span><i style={{ background: "#EF9F27" }} /> some</span>
          <span><i style={{ background: "#E24B4A" }} /> heavy</span>
          {complaints.length > 0 && <span><i className="op-pulse" style={{ background: "#4aa3ff" }} /> live reports</span>}
        </div>

        {reportMode && !pending && (
          <div className="citizen-hint">Tap the map where you see the problem</div>
        )}
        {toast && <div className="citizen-toast">{toast}</div>}
      </div>

      {/* report form (drops over the panel) */}
      {pending && (
        <div className="citizen-panel report-form">
          <div className="cp-grip" />
          <b>Report a problem</b>
          <div className="muted mono" style={{ fontSize: 11 }}>{pending[0].toFixed(5)}, {pending[1].toFixed(5)}</div>
          <select className="searchbox" style={{ width: "100%", marginTop: 8 }} value={form.vehicle_type}
            onChange={(e) => setForm({ ...form, vehicle_type: e.target.value })}>
            {VEHICLES.map((v) => <option key={v}>{v}</option>)}
          </select>
          <input className="searchbox" style={{ width: "100%", marginTop: 8 }} placeholder="What's wrong? (e.g. blocking the lane)"
            value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
            <button className="btn accent big" style={{ flex: 1 }} onClick={submitReport}>Send report</button>
            <button className="btn big" onClick={() => setPending(null)}>Cancel</button>
          </div>
        </div>
      )}

      {/* MAP tab — area detail */}
      {!pending && tab === "map" && (
        <div className="citizen-panel">
          <div className="cp-grip" />
          {!selZone ? (
            <div className="cp-empty">
              <b>Today's area check</b>
              <p className="muted">Predicted parking-obstruction for <b>{todayName}</b>. Tap any spot
                to see today's risk and the police station covering it.</p>
            </div>
          ) : (
            <AreaDetail z={selZone} patrol={patrol} todayName={todayName}
              onReport={() => { setTab("report"); setSelected(null); }} />
          )}
        </div>
      )}

      {/* TRIP tab */}
      {!pending && tab === "trip" && (
        <div className="citizen-panel">
          <div className="cp-grip" />
          <b>Plan a trip</b>
          <p className="muted" style={{ fontSize: 12, margin: "2px 0 8px" }}>
            Routes ranked by <b>today's predicted</b> parking-obstruction (from violation
            patterns, not live traffic).
          </p>
          <ZoneSearch label="From" zones={zonesT} value={trip.from}
            onPick={(z) => setTrip((t) => ({ ...t, from: z }))} onLoc={() => useMyLocation("from")} />
          <ZoneSearch label="To" zones={zonesT} value={trip.to}
            onPick={(z) => setTrip((t) => ({ ...t, to: z }))} />
          {routeLoading && <div className="muted" style={{ fontSize: 12, padding: "8px 0" }}>Finding the cleanest route…</div>}

          {sel && (
            <div className="trip-result">
              <div className="route-cards">
                {routes.map((rt, i) => (
                  <button key={i} className={"route-card" + (i === routeSel ? " active" : "")}
                    onClick={() => setRouteSel(i)} style={{ "--rc": rt.level.color }}>
                    <span className="route-card-dot" style={{ background: rt.level.color }} />
                    <span className="route-card-main">
                      <b>{rt.avoids ? "Avoids hotspots" : i === 0 ? "Best route" : `Option ${i + 1}`}</b>
                      {rt.avoids && <span className="route-avoid-tag">detour</span>}
                      <span className="muted"> · {rt.level.label}</span>
                    </span>
                    <span className="route-card-meta mono">
                      {rt.km != null ? `${rt.km} km` : "direct"}{rt.min != null ? ` · ${rt.min} min` : ""}
                    </span>
                  </button>
                ))}
              </div>

              {sel.worst?.length > 0 && (
                <>
                  <div className="muted" style={{ fontSize: 11, margin: "10px 0 4px" }}>Watch out around:</div>
                  {sel.worst.slice(0, 4).map((z) => (
                    <button key={z.id} className="trip-zone" onClick={() => pickZone(z)}>
                      <span className="dot" style={{ background: obsLevel(z.pressure).color }} />
                      <span className="trip-zone-name">{z.name}</span>
                      <span className="muted mono">{Math.round(z.pressure)}</span>
                    </button>
                  ))}
                </>
              )}
              <a className="btn accent big block" style={{ marginTop: 10 }}
                href={`https://www.google.com/maps/dir/?api=1&origin=${trip.from.lat},${trip.from.lon}&destination=${trip.to.lat},${trip.to.lon}`}
                target="_blank" rel="noreferrer"><Icon name="navigate" size={14} /> Start navigation</a>
              <div className="muted" style={{ fontSize: 10, marginTop: 8 }}>
                Roads from OpenStreetMap, ranked by parking-obstruction risk — not live traffic.
              </div>
            </div>
          )}
        </div>
      )}

      {/* REPORT tab (prompt) */}
      {!pending && tab === "report" && (
        <div className="citizen-panel">
          <div className="cp-grip" />
          <b>Report an obstruction</b>
          <p className="muted" style={{ fontSize: 12 }}>Tap the spot on the map above. Your report
            is sent to the nearest police station and shows up live for patrols.</p>
          <a className="btn big block" href={`tel:${HELPLINE}`}><Icon name="pulse" size={14} /> Or call traffic police ({HELPLINE})</a>
        </div>
      )}

      {/* bottom tabs */}
      <nav className="citizen-tabs">
        {[["map", "Area", "command"], ["trip", "Plan trip", "navigate"], ["report", "Report", "today"]].map(([k, l, ic]) => (
          <button key={k} className={"ctab" + (tab === k ? " active" : "")}
            onClick={() => { setTab(k); setPending(null); }}>
            <Icon name={ic} size={20} /><span>{l}</span>
          </button>
        ))}
      </nav>
    </div>
  );
}

function AreaDetail({ z, patrol, onReport, todayName }) {
  const lv = obsLevel(z.pressure);
  return (
    <div>
      <div className="ad-top">
        <div>
          <div className="ad-name">{z.name}</div>
          {z.station && <div className="muted" style={{ fontSize: 12 }}>{z.station} police area</div>}
        </div>
        <span className="ad-badge" style={{ background: lv.color }}>{lv.label}</span>
      </div>
      <div className="ad-today"><Icon name="today" size={12} /> Predicted for {todayName}</div>
      <p className="ad-desc">
        {lv.key === "heavy" ? "Expect heavy parking obstruction here today — vehicles frequently block the carriageway."
          : lv.key === "moderate" ? "Some parking obstruction likely here today — usually passable."
            : "Low parking-obstruction risk expected here today."}
        {z.evening_blind_spot ? " Often under-patrolled in the evening." : ""}
      </p>
      {patrol && (
        <div className="ad-patrol">
          <Icon name="shield" size={15} />
          <span><b>{patrol.units}</b> patrol unit{patrol.units === 1 ? "" : "s"} on duty now
            <span className="muted"> · {patrol.officers} officers · {z.station}</span></span>
        </div>
      )}
      <div className="ad-actions">
        <button className="btn accent big" onClick={onReport}><Icon name="today" size={14} /> Report a problem</button>
        <a className="btn big" href={`tel:${HELPLINE}`}>Call patrol</a>
        <a className="btn big" href={mapsUrl(z.lat, z.lon)} target="_blank" rel="noreferrer">Navigate</a>
      </div>
      <div className="muted" style={{ fontSize: 10, marginTop: 8 }}>
        Today's risk projected from this area's weekday × hour violation pattern — not live traffic sensors.
      </div>
    </div>
  );
}

function ZoneSearch({ label, zones, value, onPick, onLoc }) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const boxRef = useRef(null);
  const hits = useMemo(() => {
    if (q.length < 2) return [];
    const ql = q.toLowerCase();
    return zones.filter((z) => (z.name || "").toLowerCase().includes(ql) ||
      (z.station || "").toLowerCase().includes(ql)).slice(0, 6);
  }, [q, zones]);

  return (
    <div className="zone-search" ref={boxRef}>
      <span className="zs-label">{label}</span>
      <input className="searchbox" placeholder={value ? value.name : "search area / junction…"}
        value={q} onChange={(e) => { setQ(e.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)} />
      {onLoc && <button className="zs-loc" title="use my location" onClick={onLoc}><Icon name="location" size={15} /></button>}
      {open && hits.length > 0 && (
        <div className="zs-results glass">
          {hits.map((z) => (
            <div key={z.id} className="kv" onClick={() => { onPick(z); setQ(z.name); setOpen(false); }}>
              <span>{z.name}</span><span className="muted mono">{Math.round(z.pressure)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
