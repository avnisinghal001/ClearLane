import { useEffect, useMemo, useState } from "react";
import { opFeedback, opComplaint } from "../lib/api.js";
import { mapsUrl } from "../lib/format.js";
import { reasonSentence, actionChip, urgencyColor, tierLabel, ago, km, haversine }
  from "../lib/plain.js";

const CITY = [12.9716, 77.5946];

export default function OfficerView({ zones, snapshot, opByZone = {}, onChange, onExit }) {
  const [pos, setPos] = useState(null);     // [lat,lon] or null
  const [gpsOk, setGpsOk] = useState(false);
  const [busy, setBusy] = useState(null);
  const [done, setDone] = useState({});     // zone_id -> label after action
  const [reporting, setReporting] = useState(false);
  const [reportForm, setReportForm] = useState({ description: "", vehicle_type: "CAR" });
  const [confirm, setConfirm] = useState(null);

  useEffect(() => {
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(
      (p) => { setPos([p.coords.latitude, p.coords.longitude]); setGpsOk(true); },
      () => { setPos(CITY); setGpsOk(false); },
      { timeout: 6000, maximumAge: 60000 });
  }, []);

  const here = pos || CITY;
  const dist = (z) => (z.lat != null ? haversine(here[0], here[1], z.lat, z.lon) : null);

  // A2 — jobs: top by operational priority, then nearest-first when GPS is on
  const jobs = useMemo(() => {
    const opP = (z) => (opByZone[z.id]?.operational_priority ?? z.priority);
    const cands = [...zones].sort((a, b) => opP(b) - opP(a)).slice(0, 20);
    if (gpsOk) cands.sort((a, b) => dist(a) - dist(b));
    return cands.slice(0, 5);
  }, [zones, opByZone, gpsOk, pos]);

  // A3 — reports near you
  const reports = useMemo(() => {
    const cs = (snapshot?.complaints || []).filter((c) => c.status !== "resolved");
    const withD = cs.map((c) => ({ ...c, _d: gpsOk ? haversine(here[0], here[1], c.lat, c.lon) : null }));
    if (gpsOk) withD.sort((a, b) => a._d - b._d);
    return withD.slice(0, 6);
  }, [snapshot, gpsOk, pos]);

  // A5 — plain predictions
  const rising = useMemo(
    () => zones.filter((z) => z.forecast_rising).sort((a, b) => a.rank - b.rank).slice(0, 3),
    [zones]);

  const act = async (key, fn, label) => {
    setBusy(key);
    try { await fn(); if (onChange) await onChange(); if (label) setDone((d) => ({ ...d, [key]: label })); }
    finally { setBusy(null); }
  };

  async function submitReport() {
    setBusy("report");
    try {
      const r = await opComplaint({ lat: here[0], lon: here[1], ...reportForm });
      setConfirm(`Reported. Nearest hotspot: ${r.zone_name || "emerging point"}.`);
      setReporting(false); setReportForm({ description: "", vehicle_type: "CAR" });
      if (onChange) await onChange();
      setTimeout(() => setConfirm(null), 5000);
    } finally { setBusy(null); }
  }

  return (
    <div className="officer">
      <header className="off-head">
        <div><b>On Duty</b> <span className="off-loc">{gpsOk ? "📍 your location" : "📍 city centre (location off)"}</span></div>
        <button className="btn" onClick={onExit}>Full dashboard →</button>
      </header>

      {confirm && <div className="off-confirm">{confirm}</div>}

      {/* A2 jobs now */}
      <h2 className="off-h">Your jobs now</h2>
      {jobs.map((z) => {
        const op = opByZone[z.id];
        const chip = actionChip(z);
        const d = dist(z);
        return (
          <div className="off-card" key={z.id} style={{ borderLeftColor: urgencyColor(z, op) }}>
            <div className="off-card-top">
              <div className="off-name">{z.name}</div>
              {gpsOk && d != null && <div className="off-dist">{km(d)}</div>}
            </div>
            <div className="off-tier" style={{ color: urgencyColor(z, op) }}>{tierLabel(z.tier)}
              {op && <span className="off-live"> · live report active</span>}</div>
            <p className="off-reason">{reasonSentence(z)}</p>
            <div className="off-chip">{chip.icon} {chip.text}</div>
            <div className="off-actions">
              <a className="btn accent big" href={mapsUrl(z.lat, z.lon)} target="_blank" rel="noreferrer">Navigate</a>
              {done["job" + z.id]
                ? <span className="off-done">✓ {done["job" + z.id]}</span>
                : <button className="btn big" disabled={busy === "job" + z.id}
                    onClick={() => act("job" + z.id, () => opFeedback({ zone_id: z.id, kind: "action_taken" }), "Done")}>Done</button>}
            </div>
          </div>
        );
      })}

      {/* A3 reports near you */}
      <h2 className="off-h">Reports near you</h2>
      {reports.length === 0 && <p className="off-empty">No active reports nearby.</p>}
      {reports.map((c) => (
        <div className="off-card" key={c.id} style={{ borderLeftColor: "#4aa3ff" }}>
          <div className="off-card-top">
            <div className="off-name">{c.vehicle_type || "Vehicle"} reported</div>
            <div className="off-dist">{c._d != null ? km(c._d) : ago(c.created_ts)}</div>
          </div>
          <p className="off-reason">{c.description || "Obstruction reported"} · {ago(c.created_ts)}</p>
          {done["rep" + c.id]
            ? <span className="off-done">✓ {done["rep" + c.id]}</span>
            : c.zone_id && (
              <div className="off-actions wrap">
                <button className="btn big" disabled={busy === "rep" + c.id}
                  onClick={() => act("rep" + c.id, () => opFeedback({ zone_id: c.zone_id, kind: "verified_obstruction" }), "Still blocked")}>Still blocked</button>
                <button className="btn big" disabled={busy === "rep" + c.id}
                  onClick={() => act("rep" + c.id, () => opFeedback({ zone_id: c.zone_id, kind: "cleared" }), "Now clear")}>Now clear</button>
                <button className="btn" disabled={busy === "rep" + c.id}
                  onClick={() => act("rep" + c.id, () => opFeedback({ zone_id: c.zone_id, kind: "no_obstruction_found" }), "Not found")}>Not found</button>
                <button className="btn" disabled={busy === "rep" + c.id}
                  onClick={() => act("rep" + c.id, () => opFeedback({ zone_id: c.zone_id, kind: "false_alarm" }), "False report")}>False report</button>
              </div>
            )}
        </div>
      ))}

      {/* A4 report a problem */}
      <h2 className="off-h">See a problem?</h2>
      {!reporting ? (
        <button className="btn accent big block" onClick={() => setReporting(true)}>＋ Report a problem here</button>
      ) : (
        <div className="off-card" style={{ borderLeftColor: "#4aa3ff" }}>
          <p className="off-reason">Using {gpsOk ? "your current location" : "city centre"} ({here[0].toFixed(4)}, {here[1].toFixed(4)})</p>
          <input className="off-input" placeholder="What's the problem?" value={reportForm.description}
            onChange={(e) => setReportForm({ ...reportForm, description: e.target.value })} />
          <select className="off-input" value={reportForm.vehicle_type}
            onChange={(e) => setReportForm({ ...reportForm, vehicle_type: e.target.value })}>
            {["CAR", "SCOOTER", "MOTOR CYCLE", "PASSENGER AUTO", "LGV", "PRIVATE BUS", "GOODS AUTO"].map((v) => <option key={v}>{v}</option>)}
          </select>
          <div className="off-actions">
            <button className="btn accent big" disabled={busy === "report"} onClick={submitReport}>Send report</button>
            <button className="btn big" onClick={() => setReporting(false)}>Cancel</button>
          </div>
        </div>
      )}

      {/* A5 predictions strip */}
      {rising.length > 0 && (
        <div className="off-predict">
          <div className="off-predict-h">Likely to get worse next month:</div>
          {rising.map((z) => <div key={z.id} className="off-predict-row">↑ {z.name}</div>)}
          <div className="off-predict-note">Based on the last 5 months of enforcement records.</div>
        </div>
      )}
      <div style={{ height: 30 }} />
    </div>
  );
}
