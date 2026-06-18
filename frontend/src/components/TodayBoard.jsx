import { useEffect, useMemo, useState } from "react";
import { tierColor, mapsUrl } from "../lib/format.js";
import { opDispatch } from "../lib/api.js";

// "Today" emergency board. A live, weekday + hour-aware ranking of EXPECTED
// obstruction activity right now, blending each zone's historical day/hour
// enforcement pattern + the next-month forecast + live citizen reports.
// HONESTY: this is expected enforcement-demand, NOT a congestion prediction —
// ticket times reflect officer shifts, not measured traffic.
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]; // pandas dow order
const DAYS_FULL = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

function istNow() {
  const d = new Date();
  const utc = d.getTime() + d.getTimezoneOffset() * 60000;
  return new Date(utc + 5.5 * 3600000);
}
// JS getDay (0=Sun) → pandas dow (0=Mon)
const toPandasDow = (jsDay) => (jsDay + 6) % 7;

export default function TodayBoard({ zones, opByZone = {}, onSelect, onChange }) {
  const [tick, setTick] = useState(0);            // 60s clock for "live now"
  const [dowOverride, setDowOverride] = useState(null);
  const [hourOverride, setHourOverride] = useState(null);
  const [busy, setBusy] = useState(null);

  useEffect(() => {
    const t = setInterval(() => setTick((x) => x + 1), 60000);
    return () => clearInterval(t);
  }, []);

  const now = istNow();
  const dow = dowOverride ?? toPandasDow(now.getDay());
  const hour = hourOverride ?? now.getHours();
  const live = dowOverride === null && hourOverride === null;

  const ranked = useMemo(() => {
    // normalizers across the visible zones for the selected day / hour window
    const hourIdx = [hour, (hour + 1) % 24, (hour + 2) % 24]; // the upcoming shift
    let maxDow = 1, maxHour = 1;
    for (const z of zones) {
      maxDow = Math.max(maxDow, z.dow?.[dow] || 0);
      maxHour = Math.max(maxHour, hourIdx.reduce((s, h) => s + (z.hourly?.[h] || 0), 0));
    }
    const scored = zones.map((z) => {
      const op = opByZone[z.id];
      const base = op ? op.operational_priority : z.priority;
      const dowAct = (z.dow?.[dow] || 0) / maxDow;          // 0..1
      const hourAct = hourIdx.reduce((s, h) => s + (z.hourly?.[h] || 0), 0) / maxHour;
      const today = 0.40 * base + 0.20 * (z.forecast_score || 0)
        + 0.25 * dowAct * 100 + 0.15 * hourAct * 100;
      return { z, op, today: Math.round(today), dowAct, hourAct, base };
    });
    // live-reported zones are emergencies → always on top, then expected activity
    scored.sort((a, b) => {
      if (!!a.op !== !!b.op) return a.op ? -1 : 1;
      if (a.op && b.op) return b.op.operational_priority - a.op.operational_priority;
      return b.today - a.today;
    });
    return scored.slice(0, 24);
  }, [zones, opByZone, dow, hour, tick]);

  const reason = (s) => {
    const bits = [];
    if (s.op) bits.push(`live report (${(s.op.dispatch_state || "recommended").replace(/_/g, " ")})`);
    if (s.z.tier === "P1" || s.z.tier === "P2") bits.push(`${s.z.tier} chronic zone`);
    if (s.dowAct >= 0.6) bits.push(`very active on ${DAYS[dow]}`);
    if (s.hourAct >= 0.5) bits.push(`busy around ${String(hour).padStart(2, "0")}:00`);
    if (s.z.forecast_rising) bits.push("forecast rising");
    if (s.z.evening_blind_spot) bits.push("evening blind spot");
    return bits.slice(0, 3).join(" · ") || "expected activity";
  };

  const dispatch = async (id) => {
    setBusy(id);
    try { await opDispatch({ zone_id: id, state: "assigned" }); if (onChange) await onChange(); }
    finally { setBusy(null); }
  };

  const liveCount = ranked.filter((s) => s.op).length;

  return (
    <div className="panel">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", flexWrap: "wrap", gap: 8 }}>
        <h2 style={{ margin: 0 }}>Today's emergency board
          <span className="mono" style={{ color: "var(--accent)", fontSize: 13, marginLeft: 8 }}>
            {DAYS_FULL[dow]} · {String(hour).padStart(2, "0")}:00 IST{live ? " · LIVE" : ""}</span>
        </h2>
        <div style={{ display: "flex", gap: 6, alignItems: "center", fontSize: 12 }}>
          <span className="muted">Plan for:</span>
          <select className="searchbox" style={{ width: "auto" }} value={dow}
            onChange={(e) => setDowOverride(+e.target.value)}>
            {DAYS_FULL.map((d, i) => <option key={d} value={i}>{d}</option>)}
          </select>
          <select className="searchbox" style={{ width: "auto" }} value={hour}
            onChange={(e) => setHourOverride(+e.target.value)}>
            {Array.from({ length: 24 }, (_, h) => <option key={h} value={h}>{String(h).padStart(2, "0")}:00</option>)}
          </select>
          {!live && <button className="btn" onClick={() => { setDowOverride(null); setHourOverride(null); }}>Now</button>}
        </div>
      </div>
      <p className="sub">
        Expected obstruction activity for this weekday & hour window, from historical
        enforcement patterns + the next-month forecast + live citizen reports. Send
        troops top-down. <b>This is expected enforcement-demand, not a congestion
        prediction</b> — ticket times reflect officer shifts, not measured traffic.
      </p>
      {liveCount > 0 && (
        <div style={{ color: "#EF9F27", fontSize: 13, marginBottom: 8 }}>
          ⚑ {liveCount} zone{liveCount > 1 ? "s" : ""} with live citizen reports — prioritised at the top.
        </div>
      )}

      <div className="scroll">
        {ranked.map((s, i) => {
          const z = s.z;
          return (
            <div key={z.id} className="today-card"
              style={{
                display: "grid", gridTemplateColumns: "34px 1fr auto", gap: 12, alignItems: "center",
                padding: "10px 12px", marginBottom: 8, borderRadius: 8,
                background: "var(--panel2, #161b27)",
                borderLeft: `4px solid ${s.op ? "#EF9F27" : tierColor(z.tier)}`,
              }}>
              <div className="mono" style={{ fontSize: 18, fontWeight: 800, opacity: 0.6 }}>{i + 1}</div>
              <div style={{ minWidth: 0, cursor: "pointer" }} onClick={() => onSelect(z.id)}>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <b style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{z.name}</b>
                  <span className="tier-pill" style={{ background: tierColor(z.tier) }}>{z.tier}</span>
                  {s.op && <span style={{ color: "#EF9F27", fontSize: 11 }}>⚑ live</span>}
                </div>
                <div className="muted" style={{ fontSize: 12 }}>{reason(s)}</div>
                <div className="bar" style={{ marginTop: 4, maxWidth: 320 }}>
                  <span style={{ width: Math.min(100, s.today) + "%" }} /></div>
              </div>
              <div style={{ textAlign: "right", display: "flex", flexDirection: "column", gap: 4 }}>
                <div className="mono" style={{ fontSize: 20, fontWeight: 800, color: s.op ? "#EF9F27" : "var(--accent)" }}>
                  {s.op ? s.op.operational_priority : s.today}</div>
                <div className="muted" style={{ fontSize: 10 }}>{s.op ? "operational" : "today score"}</div>
                <div style={{ display: "flex", gap: 4, justifyContent: "flex-end" }}>
                  {!s.op && <button className="btn accent" disabled={busy === z.id}
                    onClick={() => dispatch(z.id)} style={{ fontSize: 11, padding: "2px 8px" }}>Dispatch</button>}
                  <a className="btn" href={mapsUrl(z.lat, z.lon)} target="_blank" rel="noreferrer"
                    style={{ fontSize: 11, padding: "2px 8px" }}>Navigate ↗</a>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
