import { useEffect, useState, useCallback, useRef } from "react";
import { api, opSnapshot, opComplaint, seedOpZones } from "./lib/api.js";
import Header from "./components/Header.jsx";
import KpiStrip from "./components/KpiStrip.jsx";
import LiveMap from "./components/LiveMap.jsx";
import PriorityTable from "./components/PriorityTable.jsx";
import FlowImpactView from "./components/FlowImpactView.jsx";
import TodayBoard from "./components/TodayBoard.jsx";
import OffendersView from "./components/OffendersView.jsx";
import ZoneDrawer from "./components/ZoneDrawer.jsx";
import TimingGap from "./components/TimingGap.jsx";
import CoverageSimulator from "./components/CoverageSimulator.jsx";
import ValidationPanel from "./components/ValidationPanel.jsx";
import ForecastView from "./components/ForecastView.jsx";
import TypologyView from "./components/TypologyView.jsx";
import StationView from "./components/StationView.jsx";
import Dispatch from "./components/Dispatch.jsx";
import OperationsConsole from "./components/OperationsConsole.jsx";
import AboutModal from "./components/AboutModal.jsx";
import JudgeTour from "./components/JudgeTour.jsx";
import OfficerView from "./components/OfficerView.jsx";

const VIEWS = [
  ["command", "Command Map"],
  ["today", "Today / Emergency"],
  ["queue", "Priority Queue"],
  ["flow_impact", "Flow Impact"],
  ["offenders", "Repeat Offenders"],
  ["operations", "Operations Loop"],
  ["timing", "Timing Gap"],
  ["coverage", "Coverage / ROI"],
  ["forecast", "Forecast"],
  ["typology", "Typology"],
  ["stations", "Station Command"],
  ["validation", "Methodology & Validation"],
];

export default function App() {
  const [view, setView] = useState("command");
  const [payload, setPayload] = useState(null);
  const [filter, setFilter] = useState(null); // KPI quick-filter
  const [selected, setSelected] = useState(null); // zone id
  const [flyTo, setFlyTo] = useState(null);
  const [hash, setHash] = useState(window.location.hash);
  const [snapshot, setSnapshot] = useState(null); // operational layer
  const [lastSync, setLastSync] = useState(null);
  const [showAbout, setShowAbout] = useState(false);
  const [showTour, setShowTour] = useState(false);
  const [isMobile, setIsMobile] = useState(window.innerWidth < 768);
  const payloadRef = useRef(null);

  const refreshSnapshot = useCallback(async () => {
    try {
      const s = await opSnapshot();
      setSnapshot(s);
      setLastSync(Date.now());
    } catch (e) { /* operational layer optional */ }
  }, []);

  useEffect(() => {
    api("/api/map/payload").then((p) => {
      setPayload(p);
      payloadRef.current = p;
      seedOpZones(p.zones);          // seed offline fallback's zone index
      refreshSnapshot();
    }).catch(console.error);
    const onHash = () => setHash(window.location.hash);
    const onResize = () => setIsMobile(window.innerWidth < 768);
    window.addEventListener("hashchange", onHash);
    window.addEventListener("resize", onResize);
    // poll the operational layer so the command centre visibly updates
    const t = setInterval(refreshSnapshot, 5000);
    return () => {
      window.removeEventListener("hashchange", onHash);
      window.removeEventListener("resize", onResize);
      clearInterval(t);
    };
  }, [refreshSnapshot]);

  const openZone = useCallback((id, fly = false) => {
    setSelected(id);
    const p = payloadRef.current;
    if (fly && p) {
      const z = p.zones.find((x) => x.id === id);
      if (z) setFlyTo([z.lat, z.lon]);
    }
  }, []);

  const submitComplaint = useCallback(async (body) => {
    const r = await opComplaint(body);
    await refreshSnapshot();
    return r;
  }, [refreshSnapshot]);

  // mobile dispatch route (hooks above all run unconditionally)
  if (hash.startsWith("#/dispatch/")) {
    return <Dispatch id={decodeURIComponent(hash.replace("#/dispatch/", ""))}
                     onChange={refreshSnapshot} />;
  }
  if (!payload) return <div style={{ padding: 40 }}>Loading ClearLane…</div>;

  const zones = payload.zones;
  const filtered = applyFilter(zones, filter);
  const opByZone = {};
  (snapshot?.zones || []).forEach((z) => { opByZone[z.zone_id] = z; });

  // Officer view: explicit #/officer, or the default on phone-width screens
  // (unless the user explicitly switched to the full dashboard via #/dashboard).
  const showOfficer = hash === "#/officer" || (isMobile && hash !== "#/dashboard");
  if (showOfficer) {
    return <OfficerView zones={zones} snapshot={snapshot} opByZone={opByZone}
      onChange={refreshSnapshot} onExit={() => { window.location.hash = "#/dashboard"; }} />;
  }

  return (
    <div className="app">
      <Header kpis={payload.kpis} onOpenZone={openZone} setView={setView}
        snapshot={snapshot} lastSync={lastSync} onSync={refreshSnapshot}
        onAbout={() => setShowAbout(true)} onTour={() => setShowTour(true)} />
      <div className="body">
        <nav className="nav">
          {VIEWS.map(([k, label]) => (
            <button key={k} className={view === k ? "active" : ""}
              onClick={() => setView(k)}>{label}</button>
          ))}
        </nav>
        <div style={{ display: "grid", gridTemplateRows: "auto 1fr", minHeight: 0 }}>
          <KpiStrip kpis={payload.kpis} filter={filter} setFilter={setFilter}
            setView={setView} snapshot={snapshot} />
          <div className={"view" + (view === "command" ? " map-view" : "")}>
            {view === "command" && (
              <LiveMap zones={filtered} flyTo={flyTo} onSelect={(id) => openZone(id)}
                opByZone={opByZone} snapshot={snapshot} onComplaint={submitComplaint} />
            )}
            {view === "queue" && (
              <PriorityTable zones={filtered} onSelect={(id) => openZone(id, true)} opByZone={opByZone} />
            )}
            {view === "flow_impact" && (
              <FlowImpactView onSelect={(id) => openZone(id, true)} />
            )}
            {view === "today" && (
              <TodayBoard zones={zones} opByZone={opByZone}
                onSelect={(id) => openZone(id, true)} onChange={refreshSnapshot} />
            )}
            {view === "offenders" && (
              <OffendersView onSelect={(id) => openZone(id, true)} />
            )}
            {view === "operations" && (
              <OperationsConsole snapshot={snapshot} onChange={refreshSnapshot}
                onSelect={(id) => openZone(id, true)} />
            )}
            {view === "timing" && <TimingGap onSelect={(id) => openZone(id, true)} />}
            {view === "coverage" && <CoverageSimulator totalZones={payload.kpis.total_zones} />}
            {view === "forecast" && <ForecastView onSelect={(id) => openZone(id, true)} />}
            {view === "typology" && <TypologyView />}
            {view === "stations" && <StationView onSelect={(id) => openZone(id, true)} />}
            {view === "validation" && <ValidationPanel />}
          </div>
        </div>
      </div>
      {selected && <ZoneDrawer id={selected} onClose={() => setSelected(null)}
        op={opByZone[selected]} onChange={refreshSnapshot} />}
      {showAbout && <AboutModal onClose={() => setShowAbout(false)} />}
      {showTour && (
        <JudgeTour onExit={() => setShowTour(false)} ctx={{
          setView, setFilter, zones,
          openZone, closeZone: () => setSelected(null),
        }} />
      )}
    </div>
  );
}

function applyFilter(zones, f) {
  if (!f) return zones;
  const map = {
    P1: (z) => z.tier === "P1",
    chronic: (z) => z.chronic,
    evening_blind_spot: (z) => z.evening_blind_spot,
    emerging: (z) => z.emerging,
    forecast_rising: (z) => z.forecast_rising,
  };
  return map[f] ? zones.filter(map[f]) : zones;
}
