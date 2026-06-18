import { opDispatch, opFeedback, opPatchStatus } from "../lib/api.js";

const NEXT = {
  recommended: "assigned", assigned: "en_route", en_route: "on_site",
  on_site: "action_taken", action_taken: "cleared",
};
const STATE_COLOR = {
  recommended: "#8893a7", assigned: "#378ADD", en_route: "#378ADD",
  on_site: "#EF9F27", action_taken: "#E6C229", cleared: "#639922",
  structural_escalation: "#b98bff",
};

export default function OperationsConsole({ snapshot, onChange, onSelect }) {
  if (!snapshot) return <div className="panel">Loading operational layer…</div>;
  const { counts, complaints = [], dispatches = [], zones = [] } = snapshot;

  const act = async (fn) => { await fn(); await onChange(); };

  return (
    <div>
      <div className="panel">
        <h2>Operations loop {snapshot.offline && <span className="flag">offline (local)</span>}</h2>
        <p className="sub">The closed operational loop: complaint → verify → dispatch → clear.
          This layer is <b>separate</b> from the historical ML scores — it adjusts a transparent
          <b> operational_priority</b> only. Cleared zones stay chronic in the historical map.</p>
        <div className="kpis" style={{ padding: 0, background: "none", border: "none" }}>
          <div className="kpi"><div className="v">{counts.active_complaints}</div><div className="l">Active complaints</div></div>
          <div className="kpi"><div className="v">{counts.open_dispatches}</div><div className="l">Open dispatches</div></div>
          <div className="kpi"><div className="v">{counts.live_zones}</div><div className="l">Live-adjusted zones</div></div>
          <div className="kpi"><div className="v">{counts.escalations}</div><div className="l">Structural escalations</div></div>
        </div>
      </div>

      <div className="grid2">
        <div className="panel">
          <h3>Live-adjusted zones</h3>
          <p className="sub">historical → +live → operational (three separate numbers)</p>
          <div className="scroll">
            <table>
              <thead><tr><th>Zone</th><th>Hist.</th><th>+Live</th><th>Op.</th><th>State</th></tr></thead>
              <tbody>
                {zones.length === 0 && <tr><td colSpan="5" className="muted">No live activity yet — submit a complaint on the Command Map.</td></tr>}
                {zones.map((z) => (
                  <tr key={z.zone_id} onClick={() => onSelect(z.zone_id)}>
                    <td>{z.name}{z.escalated && <span className="flag em"> structural</span>}</td>
                    <td className="mono">{z.historical_priority}</td>
                    <td className="mono" style={{ color: "#EF9F27" }}>+{z.live_adjustment}</td>
                    <td className="mono"><b>{z.operational_priority}</b></td>
                    <td><span style={{ color: STATE_COLOR[z.dispatch_state] || "var(--muted)" }}>{z.dispatch_state || "—"}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="panel">
          <h3>Active dispatches</h3>
          <div className="scroll">
            <table>
              <thead><tr><th>Zone</th><th>State</th><th>Advance</th></tr></thead>
              <tbody>
                {dispatches.length === 0 && <tr><td colSpan="3" className="muted">No dispatches yet.</td></tr>}
                {dispatches.map((d) => (
                  <tr key={d.id}>
                    <td className="mono">{d.zone_id}</td>
                    <td><span style={{ color: STATE_COLOR[d.state] || "var(--muted)" }}>{d.state}</span></td>
                    <td>
                      {NEXT[d.state] && (
                        <button className="btn" onClick={() => act(() => opPatchStatus(d.id, NEXT[d.state]))}>
                          → {NEXT[d.state]}</button>)}
                      {!["cleared", "structural_escalation"].includes(d.state) && (
                        <button className="btn" style={{ marginLeft: 4 }}
                          onClick={() => act(() => opPatchStatus(d.id, "structural_escalation"))}>escalate</button>)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div className="panel">
        <h3>Incoming complaints</h3>
        <div className="scroll">
          <table>
            <thead><tr><th>#</th><th>Nearest zone</th><th>Vehicle</th><th>Description</th><th>Dist.</th><th>Status</th><th>Action</th></tr></thead>
            <tbody>
              {complaints.length === 0 && <tr><td colSpan="7" className="muted">No complaints yet — click the map on the Command view to file one.</td></tr>}
              {complaints.map((c) => (
                <tr key={c.id}>
                  <td className="mono">{c.id}</td>
                  <td className="mono">{c.zone_id || "emerging point"}</td>
                  <td>{c.vehicle_type || "—"}</td>
                  <td style={{ fontSize: 12 }}>{c.description || "—"}</td>
                  <td className="mono">{c.distance_m != null ? `${c.distance_m}m` : "—"}</td>
                  <td>{c.status}</td>
                  <td>
                    {c.zone_id && <button className="btn" onClick={() =>
                      act(() => opDispatch({ zone_id: c.zone_id, complaint_id: c.id, state: "assigned" }))}>dispatch</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
