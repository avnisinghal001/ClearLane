import { useEffect, useState, useCallback, useRef } from "react";
import { api, opSnapshot, opComplaint, seedOpZones } from "./lib/api.js";
import { getAuth, logout as authLogout, slugify } from "./lib/auth.js";
import Login from "./components/Login.jsx";
import GovtConsole from "./components/GovtConsole.jsx";
import CommandCenter from "./components/CommandCenter.jsx";
import SideNav from "./components/SideNav.jsx";
import Header from "./components/Header.jsx";
import CitizenApp from "./components/CitizenApp.jsx";
import Onboarding from "./components/Onboarding.jsx";
import { Icon } from "./components/icons.jsx";
import { num } from "./lib/format.js";
import KpiStrip from "./components/KpiStrip.jsx";
import LiveMap from "./components/LiveMap.jsx";
import PriorityTable from "./components/PriorityTable.jsx";
import FlowImpactView from "./components/FlowImpactView.jsx";
import TodayBoard from "./components/TodayBoard.jsx";
import OffendersView from "./components/OffendersView.jsx";
import OfficerDemand from "./components/OfficerDemand.jsx";
import TimeLensBar from "./components/TimeLensBar.jsx";
import { defaultLens } from "./lib/timeLens.js";
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

const ANALYTICS_VIEWS = [
  ["command", "Command Map"],
  ["today", "Today / Emergency"],
  ["queue", "Priority Queue"],
  ["flow_impact", "Flow Impact"],
  ["staffing", "Staffing"],
  ["offenders", "Repeat Offenders"],
  ["operations", "Operations Loop"],
  ["timing", "Timing Gap"],
  ["coverage", "Coverage / ROI"],
  ["forecast", "Forecast"],
  ["typology", "Typology"],
  ["stations", "Station Command"],
  ["validation", "Methodology & Validation"],
];
// Government sees Force Command + every analytics view; a station sees Force
// Command first, then a scoped subset (its own zones only).
const GOVT_VIEWS = [["force", "Force Command"], ...ANALYTICS_VIEWS];
const STATION_VIEWS = [
  ["force", "Station Command"],
  ["command", "Command Map"],
  ["today", "Today / Emergency"],
  ["queue", "Priority Queue"],
  ["offenders", "Repeat Offenders"],
  ["timing", "Timing Gap"],
  ["operations", "Operations Loop"],
  ["staffing", "Staffing"],
];

// Every routable dashboard view key (union of govt + station). The active view is
// kept in the URL hash (#/<view>) so a refresh restores the same page.
const ALL_VIEW_KEYS = ["force", "command", "today", "queue", "flow_impact",
  "staffing", "offenders", "operations", "timing", "coverage", "forecast",
  "typology", "stations", "validation"];
function hashView() {
  const seg = window.location.hash.replace(/^#\/?/, "").split("/")[0];
  return ALL_VIEW_KEYS.includes(seg) ? seg : null;
}

export default function App() {
  const [auth, setAuth] = useState(getAuth());
  const [view, setView] = useState(() => hashView() || "force");
  const [navOpen, setNavOpen] = useState(false);      // mobile drawer
  const [collapsed, setCollapsed] = useState(false);  // desktop rail
  const [onboarded, setOnboarded] = useState(() => {
    try { return localStorage.getItem("cl_onboarded") === "1"; } catch { return true; }
  });
  const [metricsOpen, setMetricsOpen] = useState(typeof window !== "undefined" && window.innerWidth > 900);
  const [payload, setPayload] = useState(null);
  const [filter, setFilter] = useState(null); // KPI quick-filter
  const [selected, setSelected] = useState(null); // zone id
  const [flyTo, setFlyTo] = useState(null);
  const [hash, setHash] = useState(window.location.hash);
  const [snapshot, setSnapshot] = useState(null); // operational layer
  const [lastSync, setLastSync] = useState(null);
  const [lens, setLens] = useState(defaultLens());  // global time/prediction lens
  const [daily, setDaily] = useState(null);          // daily series for the lens
  const [showAbout, setShowAbout] = useState(false);
  const [showTour, setShowTour] = useState(false);
  const payloadRef = useRef(null);

  // navigate by updating the URL hash; the hashchange listener syncs `view`
  const go = useCallback((v) => { window.location.hash = "#/" + v; }, []);

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
    api("/api/daily").then(setDaily).catch(() => {});   // time-lens series (optional)
    const onHash = () => {
      setHash(window.location.hash);
      const v = hashView();
      if (v) setView(v);                  // restore the page from the URL
    };
    window.addEventListener("hashchange", onHash);
    // poll the operational layer so the command centre visibly updates
    const t = setInterval(refreshSnapshot, 5000);
    return () => {
      window.removeEventListener("hashchange", onHash);
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

  // search result chosen → jump to the command map and open the zone
  const onSearchPick = useCallback((id) => {
    go("command"); openZone(id, true); setNavOpen(false);
  }, [go, openZone]);

  // One-time device onboarding (hooks above all run unconditionally)
  if (!onboarded) return <Onboarding onDone={() => setOnboarded(true)} />;

  // Public citizen app — no login required
  if (hash.startsWith("#/citizen")) return <CitizenApp />;

  // RBAC gate
  if (!auth) return <Login onAuthed={(a) => { setAuth(a); go("force"); setView("force"); }} />;
  const doLogout = async () => { await authLogout(); setAuth(null); };

  // mobile dispatch route
  if (hash.startsWith("#/dispatch/")) {
    return <Dispatch id={decodeURIComponent(hash.replace("#/dispatch/", ""))}
                     onChange={refreshSnapshot} />;
  }
  if (!payload) return <div style={{ padding: 40 }}>Loading ClearLane…</div>;

  const zones = payload.zones;
  const govt = auth.role === "govt";
  // resolve the station display name for a station account from its slug
  const scopeName = govt ? null
    : (zones.find((z) => slugify(z.station || "") === auth.scope)?.station || auth.name);
  const scopedZones = govt ? zones : zones.filter((z) => (z.station || "") === scopeName);
  const filtered = applyFilter(scopedZones, filter);
  const VIEWS = govt ? GOVT_VIEWS : STATION_VIEWS;
  const opByZone = {};
  (snapshot?.zones || []).forEach((z) => { opByZone[z.zone_id] = z; });

  // Officer view: only via the explicit #/officer route (so dashboard pages work
  // and refresh-restore correctly on mobile too).
  const showOfficer = hash === "#/officer";
  if (showOfficer) {
    return <OfficerView zones={govt ? zones : scopedZones} snapshot={snapshot} opByZone={opByZone}
      stationName={govt ? null : scopeName} stationSlug={govt ? null : auth.scope}
      onChange={refreshSnapshot} onExit={() => { go("command"); }} />;
  }

  return (
    <div className="app" data-collapsed={collapsed}>
      <Header kpis={payload.kpis} onSearchPick={onSearchPick}
        snapshot={snapshot} lastSync={lastSync} onSync={refreshSnapshot}
        onAbout={() => setShowAbout(true)} onTour={() => setShowTour(true)}
        auth={auth} scopeName={scopeName}
        onMenu={() => setNavOpen(true)} />
      <div className="body">
        <SideNav views={VIEWS} view={view} onSelect={go}
          collapsed={collapsed} onToggleCollapse={() => setCollapsed((c) => !c)}
          mobileOpen={navOpen} onCloseMobile={() => setNavOpen(false)}
          role={auth.role} scopeName={scopeName} onSearchPick={onSearchPick}
          onLogout={doLogout} />
        <div className="content">
          <div className={"metrics" + (metricsOpen ? " open" : "")}>
            <button className="metrics-toggle" onClick={() => setMetricsOpen((o) => !o)}>
              <span className="mt-chev"><Icon name="chevron" size={14} /></span>
              <span className="mt-label">{metricsOpen ? "Hide metrics & date lens" : "Metrics & date lens"}</span>
              {!metricsOpen && (
                <span className="mt-summary">
                  <b>{num(payload.kpis.total_zones)}</b> zones
                  <span className="sep">·</span><b style={{ color: "var(--p1)" }}>{num(payload.kpis.P1)}</b> P1
                  <span className="sep">·</span><b style={{ color: "var(--amber)" }}>{num(snapshot?.counts?.live_zones ?? 0)}</b> live
                </span>
              )}
            </button>
            <div className="metrics-body"><div className="metrics-inner">
              <KpiStrip kpis={payload.kpis} filter={filter} setFilter={setFilter}
                setView={go} snapshot={snapshot} />
              <TimeLensBar lens={lens} setLens={setLens} daily={daily} />
            </div></div>
          </div>
          <div className={"view" + (view === "command" ? " map-view" : "")}>
            {view === "force" && govt && (
              <GovtConsole zones={zones} opByZone={opByZone} snapshot={snapshot} />
            )}
            {view === "force" && !govt && (
              <CommandCenter slug={auth.scope} name={scopeName} zones={zones}
                opByZone={opByZone} snapshot={snapshot} />
            )}
            {view === "command" && (
              <LiveMap zones={filtered} flyTo={flyTo} onSelect={(id) => openZone(id)}
                opByZone={opByZone} snapshot={snapshot} onComplaint={submitComplaint}
                lens={lens} daily={daily} />
            )}
            {view === "queue" && (
              <PriorityTable zones={filtered} onSelect={(id) => openZone(id, true)}
                opByZone={opByZone} lens={lens} daily={daily} />
            )}
            {view === "flow_impact" && (
              <FlowImpactView onSelect={(id) => openZone(id, true)} lens={lens} daily={daily} />
            )}
            {view === "today" && (
              <TodayBoard zones={scopedZones} opByZone={opByZone} daily={daily}
                onSelect={(id) => openZone(id, true)} onChange={refreshSnapshot} />
            )}
            {view === "staffing" && (
              <OfficerDemand zones={scopedZones} lens={lens} daily={daily} snapshot={snapshot}
                defaultStation={govt ? undefined : scopeName} />
            )}
            {view === "offenders" && (
              <OffendersView onSelect={(id) => openZone(id, true)}
                stationName={govt ? null : scopeName}
                areaZoneIds={govt ? null : scopedZones.map((z) => z.id)} />
            )}
            {view === "operations" && (
              <OperationsConsole snapshot={snapshot} onChange={refreshSnapshot}
                onSelect={(id) => openZone(id, true)} />
            )}
            {view === "timing" && (
              <TimingGap onSelect={(id) => openZone(id, true)}
                stationName={govt ? null : scopeName} zones={scopedZones} />
            )}
            {view === "coverage" && <CoverageSimulator totalZones={payload.kpis.total_zones} />}
            {view === "forecast" && <ForecastView onSelect={(id) => openZone(id, true)} />}
            {view === "typology" && <TypologyView />}
            {view === "stations" && <StationView onSelect={(id) => openZone(id, true)} />}
            {view === "validation" && <ValidationPanel />}
          </div>
        </div>
      </div>
      {selected && <ZoneDrawer id={selected} onClose={() => setSelected(null)}
        op={opByZone[selected]} onChange={refreshSnapshot} snapshot={snapshot} />}
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
