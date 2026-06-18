const MAPPING = [
  ["Enforcement is patrol-based & reactive", "Proactive ranked enforcement queue + exposure bias correction"],
  ["No heatmap of violations vs. likely impact", "Bias-corrected obstruction-pressure map (severity × footprint)"],
  ["Hard to prioritize zones", "Explainable Operational Priority ranking (pillars A / B / C)"],
  ["Commercial / metro / event spillover", "Zone typology + recurring-location + repeat-offender analysis"],
  ["Limited field resources", "Coverage / allocation simulator (top-K → % evidence covered)"],
  ["No closed operational loop", "Complaint → verify → dispatch → clear workflow (live layer)"],
];

export default function AboutModal({ onClose }) {
  return (
    <div className="drawer-wrap">
      <div className="drawer-bg" onClick={onClose} />
      <div className="drawer" style={{ width: 620 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h2>Gridlock Hackathon 2.0 · PS1</h2>
          <button className="btn" onClick={onClose}>✕</button>
        </div>
        <p className="sub">Theme 1 — Poor visibility on parking-induced congestion.</p>

        <div className="note" style={{ marginBottom: 14 }}>
          <b>The honest constraint:</b> the only data is 5 months of parking-violation
          tickets (Nov 2023 – Apr 2024). It contains <b>no traffic-flow, speed, delay,
          or congestion signal</b>, and ticket <i>times</i> reflect officer shifts, not
          traffic. So we never claim to measure congestion — we correct for the
          enforcement bias in the data and surface where obstruction is structural,
          where enforcement is/ isn't working, and the evening enforcement
          <b> coverage gap</b> vs the city's known peaks.
        </div>

        <h3>How ClearLane answers the brief</h3>
        <table>
          <thead><tr><th>Theme challenge</th><th>ClearLane response</th></tr></thead>
          <tbody>
            {MAPPING.map(([c, r]) => (
              <tr key={c}><td style={{ color: "var(--muted)" }}>{c}</td><td>{r}</td></tr>
            ))}
          </tbody>
        </table>

        <p className="muted" style={{ fontSize: 12, marginTop: 14 }}>
          Live complaints / officer feedback are a deployment layer — they adjust an
          <b> operational_priority</b> shown separately and never modify the historical
          ML scores. Full method in <span className="mono">docs/METHODOLOGY.md</span> and
          <span className="mono"> docs/PRODUCT_SCOPE.md</span>.
        </p>
      </div>
    </div>
  );
}
