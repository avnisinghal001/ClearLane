import { useEffect, useState } from "react";
import { isLive } from "../lib/api.js";
import { nowIST } from "../lib/format.js";
import { Icon } from "./icons.jsx";
import SearchBox from "./SearchBox.jsx";

function syncLabel(ts) {
  if (!ts) return "never";
  const s = Math.round((Date.now() - ts) / 1000);
  if (s < 5) return "just now";
  if (s < 60) return `${s}s ago`;
  return `${Math.round(s / 60)}m ago`;
}

export default function Header({ kpis, onSearchPick, snapshot, lastSync,
                                onSync, onAbout, onTour, auth, scopeName, onLogout, onMenu }) {
  const [clock, setClock] = useState(nowIST());
  const [, setTick] = useState(0);

  useEffect(() => {
    const t = setInterval(() => { setClock(nowIST()); setTick((x) => x + 1); }, 1000);
    return () => clearInterval(t);
  }, []);

  return (
    <header className="header">
      <button className="icon-btn hamburger" onClick={onMenu} aria-label="menu">
        <Icon name="menu" size={24} />
      </button>
      <div className="wordmark">
        <span className="brand-mark hdr-mark"><Icon name="lane" size={28} strokeWidth={2} /></span>
        Clear<span className="lane">Lane</span>
      </div>
      <div className="meta hide-lg">{kpis.data_window}</div>
      <div className="spacer" />

      <SearchBox onPick={onSearchPick} cls="hide-md" />

      {snapshot?.counts && (
        <span className="meta hide-lg" title="operational layer">
          <span className="op-pulse" style={{ color: "var(--amber)" }}>⚑</span> {snapshot.counts.open_dispatches} dispatch · {snapshot.counts.active_complaints} complaint
        </span>
      )}
      <button className="icon-btn hide-md" onClick={onSync}
        title={`refresh operational data · sync ${syncLabel(lastSync)}`}>
        <Icon name="sync" size={18} />
      </button>
      <button className="btn hide-md" onClick={() => { window.location.hash = "#/officer"; }}>
        <Icon name="location" size={14} /> On Duty</button>
      <button className="btn hide-lg" onClick={onAbout}>About</button>
      <button className="btn accent hide-md" onClick={onTour}>▶ Tour</button>
      <span className="mono meta hide-lg">{clock}</span>
      {auth && (
        <span className="badge role-badge" title="signed-in role"
          style={{ color: auth.role === "govt" ? "var(--good)" : "var(--accent)",
                   borderColor: auth.role === "govt" ? "#2c6b46" : "#2b5688" }}>
          <Icon name={auth.role === "govt" ? "building" : "shield"} size={12} />
          <span className="hide-sm">{auth.role === "govt" ? "GOVT" : (scopeName || auth.name)}</span>
        </span>
      )}
      <span className={"badge " + (isLive() ? "live" : "demo")}>
        <span className="live-dot" /> {isLive() ? "LIVE" : "DEMO"}
      </span>
      {auth && <button className="icon-btn" onClick={onLogout} title="sign out">
        <Icon name="logout" size={16} />
      </button>}
    </header>
  );
}
