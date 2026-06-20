import { useEffect, useMemo, useState } from "react";
import { MapContainer, TileLayer, CircleMarker, Popup, Tooltip, useMap, useMapEvents } from "react-leaflet";
import { api } from "../lib/api.js";
import { HeatLayer, HeatToggle, HEAT_METRICS, heatPoints as buildHeatPoints } from "./HeatLayer.jsx";
import { tierColor, mapsUrl } from "../lib/format.js";
import { reasonSentence } from "../lib/plain.js";
import { isActive, activityField, lensLabel } from "../lib/timeLens.js";
import MapPanel from "./MapPanel.jsx";
import { Icon } from "./icons.jsx";
import WhatNow from "./WhatNow.jsx";

const CENTER = [12.9716, 77.5946];
const BASES = {
  dark: "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
  light: "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
  osm: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
};
const TYPO_COLORS = ["#378ADD", "#EF9F27", "#7fe0a0", "#b98bff", "#ff8a8a",
  "#E6C229", "#46c5c5", "#e07fc0"];
const STATE_COLOR = {
  on_site: "#EF9F27", action_taken: "#E6C229", cleared: "#639922",
  structural_escalation: "#b98bff", assigned: "#378ADD", en_route: "#378ADD",
};

function FlyTo({ pos }) {
  const map = useMap();
  useEffect(() => { if (pos) map.flyTo(pos, 16, { duration: 0.8 }); }, [pos]);
  return null;
}

function ClickToComplain({ active, onPick }) {
  useMapEvents({ click(e) { if (active) onPick([e.latlng.lat, e.latlng.lng]); } });
  return null;
}

// heatmap layer + metrics now live in ./HeatLayer.jsx (shared across all maps)

export default function LiveMap({ zones, flyTo, onSelect, opByZone = {}, snapshot,
                                 onComplaint, defaultSimple = false,
                                 lens = { mode: "all" }, daily = null }) {
  const [base, setBase] = useState("dark");
  const [noTiles, setNoTiles] = useState(false);
  const [simple, setSimple] = useState(defaultSimple);
  const [hourOn, setHourOn] = useState(false);
  const [hour, setHour] = useState(18);
  const [colorMode, setColorMode] = useState("tier");
  const [showEvidence, setShowEvidence] = useState(false);
  const [showRings, setShowRings] = useState(true);
  const [evidence, setEvidence] = useState([]);
  const [complainMode, setComplainMode] = useState(false);
  const [pending, setPending] = useState(null); // [lat,lon] awaiting complaint form
  const [form, setForm] = useState({ description: "", vehicle_type: "CAR", vehicle_number: "" });
  const [toast, setToast] = useState(null);
  const [replayOn, setReplayOn] = useState(false);
  const [replay, setReplay] = useState(null);
  const [rIdx, setRIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(900); // ms per period
  const [showHeat, setShowHeat] = useState(false);   // points view by default; toggle to heatmap
  const [heatMetric, setHeatMetric] = useState("pressure");
  const wide = typeof window !== "undefined" && window.innerWidth > 900;
  const [statsOpen, setStatsOpen] = useState(wide);
  const [legendOpen, setLegendOpen] = useState(wide);

  useEffect(() => {
    if (showEvidence && evidence.length === 0) {
      api("/api/evidence-points").then((p) => setEvidence(p.slice(0, 3000))).catch(() => {});
    }
  }, [showEvidence]);

  useEffect(() => {
    if (replayOn && !replay) api("/api/replay-frames").then(setReplay).catch(() => setReplayOn(false));
  }, [replayOn]);

  useEffect(() => {
    if (!playing || !replay) return;
    const t = setInterval(() => setRIdx((i) => (i + 1) % replay.periods.length), speed);
    return () => clearInterval(t);
  }, [playing, replay, speed]);

  const rMax = useMemo(() => {
    if (!replay) return 1;
    let m = 1; for (const z of replay.zones) for (const c of z.counts) if (c > m) m = c;
    return m;
  }, [replay]);

  const typoList = useMemo(
    () => [...new Set(zones.map((z) => z.typology))].filter(Boolean), [zones]);
  // flow-impact gradient: accent-blue (low) → red (high). v in 0..100.
  const flowColor = (v) => {
    const t = Math.max(0, Math.min(1, (v ?? 0) / 100));
    const a = [55, 138, 221], b = [226, 75, 74];
    const c = a.map((x, i) => Math.round(x + (b[i] - x) * t));
    return `rgb(${c[0]},${c[1]},${c[2]})`;
  };
  const colorOf = (z) =>
    colorMode === "typology"
      ? TYPO_COLORS[typoList.indexOf(z.typology) % TYPO_COLORS.length]
      : colorMode === "flow_impact"
        ? flowColor(z.flow_impact)
        : tierColor(z.tier);

  // Time-lens activity field (window-aware sizing/filtering).
  const lensOn = isActive(lens) && !hourOn && !replayOn;
  const actField = useMemo(
    () => activityField(zones, lens, daily), [zones, lens, daily]);

  // Simple view → only P1/P2. Hour filter → only zones active in that hour.
  // Time lens → only zones with activity in the selected window.
  const display = useMemo(() => {
    let d = simple ? zones.filter((z) => z.tier === "P1" || z.tier === "P2") : zones;
    if (hourOn) d = d.filter((z) => (z.hourly?.[hour] || 0) > 0);
    if (lensOn) d = d.filter((z) => (actField.vals[z.id] || 0) > 0);
    return d;
  }, [zones, simple, hourOn, hour, lensOn, actField]);

  const hourMax = useMemo(() => {
    if (!hourOn) return 1;
    let m = 1; for (const z of zones) { const v = z.hourly?.[hour] || 0; if (v > m) m = v; }
    return m;
  }, [zones, hourOn, hour]);

  // heat points for the selected PS1 metric (shared builder)
  const heatPoints = useMemo(() => buildHeatPoints(display, heatMetric), [display, heatMetric]);

  const radius = (z) => {
    if (hourOn) return 3 + ((z.hourly?.[hour] || 0) / hourMax) * 15;
    if (lensOn) return 3 + ((actField.vals[z.id] || 0) / actField.max) * 16;
    const base = 4 + (z.pressure / 100) * 11;
    return simple ? base + 4 : base;
  };

  const complaints = snapshot?.complaints || [];
  const liveZones = snapshot?.zones || [];
  const deployedByStation = useMemo(() => {
    const m = {};
    for (const d of (snapshot?.dispatches || [])) {
      if (["cleared", "structural_escalation"].includes(d.state)) continue;
      if (d.station) m[d.station] = (m[d.station] || 0) + 1;
    }
    return m;
  }, [snapshot]);

  async function submitComplaint() {
    try {
      const r = await onComplaint({ lat: pending[0], lon: pending[1], ...form });
      const veh = form.vehicle_number ? `${form.vehicle_number.toUpperCase()} · ` : "";
      const stn = r.station ? ` · ${r.station} station` : "";
      setToast(`Complaint filed → ${veh}${r.zone_name || "emerging point"}${stn}`);
    } catch (e) {
      setToast(`Rejected: ${e.message}`);
    }
    setPending(null); setComplainMode(false);
    setForm({ description: "", vehicle_type: "CAR", vehicle_number: "" });
    setTimeout(() => setToast(null), 4000);
  }

  return (
    <>
      <HeatToggle on={showHeat} onToggle={setShowHeat}
        metric={heatMetric} setMetric={setHeatMetric} pos="tc" />
      {!hourOn && !replayOn && <WhatNow zones={zones} opByZone={opByZone} onSelect={onSelect} />}

      <MapPanel title="Map layers &amp; view" icon="layers" pos="tl">
        <div className="map-sec-label">View mode</div>
        <label className="toggle" style={{ borderColor: "var(--accent)" }}>
          <input type="checkbox" checked={simple}
          onChange={(e) => setSimple(e.target.checked)} /> Simple view (P1 / P2 only)</label>
        <label className="toggle"><input type="checkbox" checked={hourOn}
          onChange={(e) => setHourOn(e.target.checked)} /> Hour-of-day activity</label>
        <label className="toggle"><input type="checkbox" checked={complainMode}
          onChange={(e) => { setComplainMode(e.target.checked); setPending(null); }} />
          File complaint (click map)</label>
        {!simple && <>
          <div className="map-sec-label">Overlays</div>
          <label className="toggle"><input type="checkbox" checked={showRings}
            onChange={(e) => setShowRings(e.target.checked)} /> Evening blind-spot rings</label>
          <label className="toggle"><input type="checkbox" checked={showEvidence}
            onChange={(e) => setShowEvidence(e.target.checked)} /> Evidence points</label>
          <label className="toggle"><input type="checkbox" checked={replayOn}
            onChange={(e) => { setReplayOn(e.target.checked); setPlaying(e.target.checked); }} /> Historical replay</label>
          <div className="map-sec-label">Color zones by</div>
          <label className="toggle">
            <select value={colorMode} onChange={(e) => setColorMode(e.target.value)}
              style={{ flex: 1, background: "transparent", color: "inherit", border: "none" }}>
              <option value="tier">Priority tier</option>
              <option value="typology">Typology cluster</option>
              <option value="flow_impact">Flow impact</option>
            </select></label>
        </>}
        <div className="map-sec-label">Base map</div>
        <select className="searchbox" value={noTiles ? "plain" : base}
          onChange={(e) => { if (e.target.value === "plain") setNoTiles(true); else { setNoTiles(false); setBase(e.target.value); } }}
          style={{ width: "100%" }}>
          <option value="dark">Dark (satellite-style)</option><option value="light">Light</option>
          <option value="osm">OpenStreetMap</option><option value="plain">Plain (offline)</option>
        </select>
      </MapPanel>

      <div className={"map-overlay stats collapsible" + (statsOpen ? " open" : "")}>
        <button className="ov-head" onClick={() => setStatsOpen((o) => !o)}>
          <span className="mono ov-big">{display.length}</span>
          <span className="ov-cap">{hourOn ? `@ ${String(hour).padStart(2, "0")}:00` : "zones shown"}</span>
          <span className="ov-chev"><Icon name="chevron" size={14} /></span>
        </button>
        <div className="ov-body"><div className="ov-inner">
          <div style={{ fontSize: 11 }}>
            P1 {display.filter((z) => z.tier === "P1").length} · blind {display.filter((z) => z.evening_blind_spot).length}
          </div>
          {liveZones.length > 0 && <div style={{ marginTop: 4, fontSize: 11, color: "#EF9F27" }}>⚑ {liveZones.length} live ops</div>}
          {lensOn && <div style={{ marginTop: 4, fontSize: 10, color: "var(--accent)" }}>📅 {lensLabel(lens, daily)} · size = expected activity</div>}
        </div></div>
      </div>

      {complainMode && !pending && (
        <div className="map-overlay" style={{ top: 16, left: "50%", transform: "translateX(-50%)" }}>
          Click anywhere on the map to drop a complaint at that coordinate.
        </div>
      )}
      {toast && <div className="map-overlay" style={{ top: 16, left: "50%", transform: "translateX(-50%)", zIndex: 1300 }}>{toast}</div>}

      {pending && (
        <div className="map-overlay" style={{ top: 60, left: "50%", transform: "translateX(-50%)", zIndex: 1200, width: 280 }}>
          <b>New complaint</b>
          <div className="mono muted" style={{ fontSize: 11 }}>{pending[0].toFixed(5)}, {pending[1].toFixed(5)}</div>
          <input className="searchbox mono" style={{ width: "100%", margin: "6px 0 0", textTransform: "uppercase" }}
            placeholder="vehicle number (e.g. KA01AB1234)"
            value={form.vehicle_number} onChange={(e) => setForm({ ...form, vehicle_number: e.target.value })} />
          <input className="searchbox" style={{ width: "100%", margin: "6px 0" }} placeholder="description"
            value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          <select className="searchbox" style={{ width: "100%" }} value={form.vehicle_type}
            onChange={(e) => setForm({ ...form, vehicle_type: e.target.value })}>
            {["CAR", "SCOOTER", "MOTOR CYCLE", "PASSENGER AUTO", "LGV", "PRIVATE BUS", "GOODS AUTO"].map((v) => <option key={v}>{v}</option>)}
          </select>
          <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
            <button className="btn accent" onClick={submitComplaint}>Submit</button>
            <button className="btn" onClick={() => setPending(null)}>Cancel</button>
          </div>
        </div>
      )}

      {hourOn && (
        <div className="map-overlay" style={{ bottom: 16, left: "50%", transform: "translateX(-50%)", zIndex: 700, width: 460, maxWidth: "92vw" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
            <b>Activity by hour of day</b>
            <span className="mono" style={{ color: hour >= 17 && hour < 21 ? "#EF9F27" : "var(--accent)" }}>
              {String(hour).padStart(2, "0")}:00{hour >= 17 && hour < 21 ? " · evening rush" : ""}</span>
          </div>
          <input type="range" min="0" max="23" value={hour} className="slider"
            onChange={(e) => setHour(+e.target.value)} style={{ margin: "6px 0" }} />
          <div className="muted" style={{ fontSize: 11 }}>
            Drag toward the evening — the map empties out. Recorded enforcement activity by hour,
            <b> not live traffic</b>; ticket times reflect officer shifts.
          </div>
        </div>
      )}

      {replayOn && replay && (
        <div className="map-overlay" style={{ top: 16, left: "50%", transform: "translateX(-50%)", zIndex: 700, width: 420, maxWidth: "90vw" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
            <b>Historical enforcement replay</b>
            <span className="mono" style={{ color: "var(--accent)" }}>{replay.labels[rIdx]}</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, margin: "6px 0" }}>
            <button className="btn" onClick={() => setPlaying((p) => !p)}>{playing ? "❚❚" : "▶"}</button>
            <input type="range" min="0" max={replay.periods.length - 1} value={rIdx} className="slider"
              onChange={(e) => { setPlaying(false); setRIdx(+e.target.value); }} />
            <select className="searchbox" style={{ width: "auto" }} value={speed}
              onChange={(e) => setSpeed(+e.target.value)}>
              <option value="1600">0.5×</option><option value="900">1×</option><option value="450">2×</option>
            </select>
          </div>
          <div className="muted" style={{ fontSize: 11 }}>Aggregated tickets recorded per month — NOT live
            traffic. Strategic ranking is unchanged; this shows recorded enforcement activity over time.</div>
        </div>
      )}

      <div className={"map-overlay legend collapsible" + (legendOpen ? " open" : "")}>
        <button className="ov-head" onClick={() => setLegendOpen((o) => !o)}>
          <span className="ov-cap"><b>Legend</b></span>
          <span className="ov-chev"><Icon name="chevron" size={14} /></span>
        </button>
        <div className="ov-body"><div className="ov-inner">
        {showHeat && (
          <div style={{ marginBottom: 8 }}>
            <div className="row" style={{ fontWeight: 700 }}>{HEAT_METRICS[heatMetric].label}</div>
            <div className="heat-bar" />
            <div className="row muted" style={{ fontSize: 10, justifyContent: "space-between" }}>
              <span>low</span><span>high</span></div>
            <div className="row muted" style={{ fontSize: 10 }}>modeled from tickets · not measured congestion</div>
          </div>
        )}
        {colorMode === "tier" &&
          ["P1", "P2", "P3", "P4"].map((t) => (
            <div className="row" key={t}><span className="dot" style={{ background: tierColor(t) }} /> {t}</div>))}
        {colorMode === "typology" &&
          typoList.slice(0, 8).map((t, i) => (
            <div className="row" key={t}><span className="dot" style={{ background: TYPO_COLORS[i % 8] }} /> {t}</div>))}
        {colorMode === "flow_impact" && (
          <>
            <div className="row"><span className="dot" style={{ background: flowColor(15) }} /> low flow-impact</div>
            <div className="row"><span className="dot" style={{ background: flowColor(60) }} /> medium</div>
            <div className="row"><span className="dot" style={{ background: flowColor(95) }} /> high (junction / arterial)</div>
            <div className="row muted" style={{ fontSize: 10 }}>modeled proxy · not measured congestion</div>
          </>
        )}
        {liveZones.length > 0 && <div className="row" style={{ marginTop: 4 }}><span className="dot op-pulse" style={{ background: "#4aa3ff" }} /> live complaint / ops</div>}
        <div className="row muted" style={{ marginTop: 6, fontSize: 10 }}>size = obstruction pressure</div>
        </div></div>
      </div>

      <MapContainer center={CENTER} zoom={12} preferCanvas>
        {!noTiles && (
          <TileLayer url={BASES[base]} attribution="© OpenStreetMap, © CARTO"
            eventHandlers={{ tileerror: () => setNoTiles(true) }} />
        )}
        <FlyTo pos={flyTo} />
        <ClickToComplain active={complainMode} onPick={setPending} />

        {showHeat && !replayOn && heatPoints.length > 0 && <HeatLayer points={heatPoints} />}

        {showEvidence && evidence.map((p, i) => (
          <CircleMarker key={"e" + i} center={[p.lat, p.lon]} radius={1.6}
            pathOptions={{ color: "#5b6472", weight: 0, fillOpacity: 0.5 }} />
        ))}

        {replayOn && replay && replay.zones.map((z) => {
          const c = z.counts[rIdx]; if (!c) return null;
          return (
            <CircleMarker key={"rp" + z.id} center={[z.lat, z.lon]} radius={3 + (c / rMax) * 16}
              pathOptions={{ color: tierColor(z.tier), weight: 0, fillColor: tierColor(z.tier), fillOpacity: 0.5 }}>
              <Popup><b>{z.name}</b><br />{replay.labels[rIdx]}: {c} tickets recorded</Popup>
            </CircleMarker>
          );
        })}

        {!replayOn && !showHeat && display.map((z) => {
          const op = opByZone[z.id];
          return (
            <CircleMarker key={z.id} center={[z.lat, z.lon]} radius={radius(z)}
              pathOptions={{ color: op ? (STATE_COLOR[op.dispatch_state] || "#4aa3ff") : colorOf(z),
                weight: op ? 3 : (z.emerging ? 2 : 1),
                fillColor: colorOf(z), fillOpacity: 0.55,
                dashArray: z.forecast_rising ? "3" : null }}
              eventHandlers={{ click: () => onSelect(z.id) }}>
              <Popup>
                {simple ? (
                  <>
                    <b>{z.name}</b> — <span style={{ color: tierColor(z.tier) }}>{z.tier}</span><br />
                    {reasonSentence(z)}<br />
                    <a href={mapsUrl(z.lat, z.lon)} target="_blank" rel="noreferrer">Navigate ↗</a>
                  </>
                ) : (
                  <>
                    <b>{z.name}</b> — <span style={{ color: tierColor(z.tier) }}>{z.tier}</span><br />
                    <span className="mono" style={{ fontSize: 11 }}>zone {z.id}</span><br />
                    Priority {z.priority} · pressure {z.pressure}<br />
                    {op && <span style={{ color: "#EF9F27" }}>⚑ operational {op.operational_priority} (hist {op.historical_priority} +{op.live_adjustment})<br /></span>}
                    {z.evening_blind_spot && <span style={{ color: "#EF9F27" }}>⚠ evening blind spot<br /></span>}
                    <i style={{ fontSize: 11 }}>{z.intervention}</i><br />
                    <a href={mapsUrl(z.lat, z.lon)} target="_blank" rel="noreferrer">Open in Google Maps ↗</a>
                  </>
                )}
              </Popup>
            </CircleMarker>
          );
        })}

        {!replayOn && !hourOn && !showHeat && showRings && zones.filter((z) => z.evening_blind_spot).map((z) => (
          <CircleMarker key={"r" + z.id} center={[z.lat, z.lon]} radius={radius(z) + 5}
            pathOptions={{ color: "#EF9F27", weight: 1.3, fill: false, dashArray: "4" }} />
        ))}

        {/* operational complaint pulses */}
        {complaints.map((c) => (
          <CircleMarker key={"c" + c.id} center={[c.lat, c.lon]} radius={6}
            pathOptions={{ color: "#4aa3ff", weight: 2, fillColor: "#4aa3ff",
              fillOpacity: 0.5, className: "op-pulse" }}>
            {c.vehicle_number && (
              <Tooltip permanent direction="top" offset={[0, -6]} className="veh-tag">
                {c.vehicle_number}</Tooltip>
            )}
            <Popup>
              <b>Complaint #{c.id}</b>{c.vehicle_number && <> · <span className="mono">{c.vehicle_number}</span></>}<br />
              {c.vehicle_type || "—"} · {c.description || "no description"}<br />
              {c.station && <>nearest station: <b>{c.station}</b>
                {deployedByStation[c.station] ? ` · ${deployedByStation[c.station]} on duty` : ""}<br /></>}
              status: {c.status}
            </Popup>
          </CircleMarker>
        ))}
      </MapContainer>
    </>
  );
}
