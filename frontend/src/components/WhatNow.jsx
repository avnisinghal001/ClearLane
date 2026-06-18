import { tierColor } from "../lib/format.js";

// Deterministic "next best action" from existing fields — no model call, no LLM.
export default function WhatNow({ zones, opByZone = {}, onSelect }) {
  if (!zones || zones.length === 0) return null;

  // pick the most urgent live-adjusted zone; else the top historical priority zone
  const live = Object.values(opByZone)
    .filter((z) => z.dispatch_state !== "cleared")
    .sort((a, b) => b.operational_priority - a.operational_priority)[0];
  let target, op = null;
  if (live) {
    target = zones.find((z) => z.id === live.zone_id) || zones[0];
    op = live;
  } else {
    target = [...zones].sort((a, b) => a.rank - b.rank)[0];
  }
  if (!target) return null;

  const reasons = [];
  if (target.chronic) reasons.push("chronic");
  if (target.pressure >= 70) reasons.push("high obstruction pressure");
  if (target.responsiveness === "resistant") reasons.push("enforcement-resistant across months");
  if (target.habitual) reasons.push("habitual repeat vehicles");
  if (target.evening_blind_spot) reasons.push("evening blind spot");
  const confidence = target.n_tickets >= 30 ? "high" : "medium";

  return (
    <div className="map-overlay" style={{ bottom: 16, left: "50%", transform: "translateX(-50%)",
      zIndex: 600, width: 560, maxWidth: "90vw", borderColor: "var(--accent)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <b style={{ color: "var(--accent)" }}>▸ What to do now</b>
        <span className="muted" style={{ fontSize: 11 }}>deterministic · confidence {confidence}</span>
      </div>
      <div style={{ margin: "4px 0", cursor: "pointer" }} onClick={() => onSelect(target.id)}>
        Dispatch a team to <b>{target.name}</b>
        {target.station ? <span className="muted"> ({target.station})</span> : null}.{" "}
        <span style={{ fontSize: 12 }}>{target.intervention}.</span>
        {reasons.length > 0 && <span className="muted" style={{ fontSize: 12 }}> — {reasons.join(", ")}.</span>}
      </div>
      <div style={{ display: "flex", gap: 14, fontSize: 12, alignItems: "center" }}>
        <span><span className="muted">tier </span><span className="tier-pill" style={{ background: tierColor(target.tier) }}>{target.tier}</span></span>
        <span><span className="muted">historical </span><b>{op ? op.historical_priority : target.priority}</b></span>
        {op && <span style={{ color: "#EF9F27" }}>+live {op.live_adjustment}</span>}
        {op && <span><span className="muted">operational </span><b>{op.operational_priority}</b></span>}
        {op?.dispatch_state && <span className="muted">state: {op.dispatch_state}</span>}
        <span className="mono muted">{target.lat.toFixed(4)},{target.lon.toFixed(4)}</span>
      </div>
    </div>
  );
}
