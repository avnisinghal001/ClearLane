import { useEffect, useState } from "react";
import { isLive, api } from "../lib/api.js";
import { nowIST } from "../lib/format.js";

function syncLabel(ts) {
  if (!ts) return "never";
  const s = Math.round((Date.now() - ts) / 1000);
  if (s < 5) return "just now";
  if (s < 60) return `${s}s ago`;
  return `${Math.round(s / 60)}m ago`;
}

export default function Header({ kpis, onOpenZone, setView, snapshot, lastSync,
                                onSync, onAbout, onTour }) {
  const [clock, setClock] = useState(nowIST());
  const [q, setQ] = useState("");
  const [hits, setHits] = useState([]);
  const [, setTick] = useState(0);

  useEffect(() => {
    const t = setInterval(() => { setClock(nowIST()); setTick((x) => x + 1); }, 1000);
    return () => clearInterval(t);
  }, []);

  async function search(v) {
    setQ(v);
    if (v.length < 2) return setHits([]);
    try {
      const r = await api("/api/search?q=" + encodeURIComponent(v));
      setHits(r.slice(0, 6));
    } catch {
      setHits([]);
    }
  }

  return (
    <header className="header">
      <div className="wordmark">Clear<span className="lane">Lane</span></div>
      <div className="meta">{kpis.data_window}</div>
      <div className="spacer" />
      <div style={{ position: "relative" }}>
        <input className="searchbox" placeholder="Search junction / zone…"
          value={q} onChange={(e) => search(e.target.value)} />
        {hits.length > 0 && (
          <div className="map-overlay" style={{ position: "absolute", top: 32, right: 0, zIndex: 2000 }}>
            {hits.map((h) => (
              <div key={h.id} className="kv" style={{ cursor: "pointer" }}
                onClick={() => { setView("command"); onOpenZone(h.id, true); setHits([]); setQ(""); }}>
                <span>{h.label}</span><span className="muted mono">{h.tier}</span>
              </div>
            ))}
          </div>
        )}
      </div>
      {snapshot?.counts && (
        <span className="meta" title="operational layer">
          ⚑ {snapshot.counts.open_dispatches} dispatch · {snapshot.counts.active_complaints} complaint
        </span>
      )}
      <span className="meta mono" title="last operational sync">sync {syncLabel(lastSync)}</span>
      <button className="btn" onClick={onSync} title="refresh operational data">⟳</button>
      <button className="btn" onClick={() => { window.location.hash = "#/officer"; }}>On Duty</button>
      <button className="btn" onClick={onAbout}>About / PS1</button>
      <button className="btn accent" onClick={onTour}>▶ Judge Tour</button>
      <span className="mono meta">{clock}</span>
      <span className={"badge " + (isLive() ? "live" : "demo")}>
        {isLive() ? "● LIVE" : "● DEMO (offline)"}
      </span>
    </header>
  );
}
