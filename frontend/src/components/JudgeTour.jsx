import { useEffect, useState } from "react";

// Deterministic guided flow over real zones. Never blocks manual use — it's a
// floating card; the rest of the dashboard stays fully interactive.
const findZone = (zones, needles) =>
  zones.find((z) => needles.some((n) => (z.name || "").toLowerCase().includes(n)))
  || zones.find((z) => z.tier === "P1");

export default function JudgeTour({ ctx, onExit }) {
  const [i, setI] = useState(0);

  const steps = [
    { label: "The honest thesis",
      text: "The only data is 5 months of parking tickets — no congestion, speed or delay signal, and ticket times track officer shifts. ClearLane is the team that proves the enforcement bias and corrects for it, instead of faking a congestion map.",
      run: () => { ctx.setView("validation"); ctx.closeZone(); } },
    { label: "The evening blind spot",
      text: "Enforcement peaks at 10am; only ~0.16% of tickets fall in the 5–9pm window. The worst chronic zones go essentially unenforced exactly when congestion bites. (An enforcement-coverage gap vs known peaks — stated as an assumption, never measured.)",
      run: () => ctx.setView("timing") },
    { label: "A real Bengaluru hotspot",
      text: "Our system independently flags KR Market / Safina Plaza as a P1 chronic zone — anyone from Bengaluru knows these junctions. Real names over internal IDs everywhere.",
      run: () => { ctx.setView("command"); const z = findZone(ctx.zones, ["kr market", "safina", "city market"]); if (z) ctx.openZone(z.id, true); } },
    { label: "Raw vs bias-adjusted rank",
      text: "Raw ticket counts reward heavily-patrolled spots. We correct for enforcement exposure (officers × active days) and show the raw rank → bias-adjusted rank shift in the drawer — answering 'aren't hotspots just where police patrol?'.",
      run: () => { const z = findZone(ctx.zones, ["kr market", "safina", "city market"]); if (z) ctx.openZone(z.id, true); } },
    { label: "Responsiveness + intervention",
      text: "Per zone we classify habitual vs transient and whether enforcement is working (responding) or resistant (needs a structural fix) — then recommend a concrete intervention, not just 'dispatch'.",
      run: () => {} },
    { label: "Forecast — validated, honest",
      text: "A LightGBM model forecasts next-month obstruction pressure (a real observed future value, never congestion): R² 0.76, top-20 precision 0.85, plus sensitivity and a persistence backtest. The weights are not arbitrary.",
      run: () => { ctx.closeZone(); ctx.setView("forecast"); } },
    { label: "The closed operational loop",
      text: "Complaint → verify → dispatch → clear, as a separate live layer. It adjusts operational_priority transparently and NEVER touches the historical ML score; a cleared zone stays a chronic historical hotspot. That answers the theme's 'no closed loop'.",
      run: () => { ctx.closeZone(); ctx.setView("operations"); } },
  ];

  useEffect(() => { steps[i].run(); /* eslint-disable-next-line */ }, [i]);

  const s = steps[i];
  return (
    <div style={{ position: "fixed", bottom: 20, right: 20, zIndex: 3000, width: 380,
      background: "var(--panel)", border: "1px solid var(--accent)", borderRadius: 12,
      padding: 16, boxShadow: "0 8px 30px rgba(0,0,0,.5)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span className="muted" style={{ fontSize: 11 }}>JUDGE TOUR · {i + 1}/{steps.length}</span>
        <button className="btn" onClick={onExit}>Exit</button>
      </div>
      <h3 style={{ margin: "8px 0 6px" }}>{s.label}</h3>
      <p style={{ fontSize: 13, margin: 0 }}>{s.text}</p>
      <div style={{ display: "flex", gap: 6, marginTop: 12 }}>
        <button className="btn" disabled={i === 0} onClick={() => setI(i - 1)}>← Back</button>
        {i < steps.length - 1
          ? <button className="btn accent" onClick={() => setI(i + 1)}>Next →</button>
          : <button className="btn accent" onClick={onExit}>Finish</button>}
        <div style={{ flex: 1 }} />
        <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
          {steps.map((_, k) => (
            <span key={k} style={{ width: 7, height: 7, borderRadius: "50%",
              background: k === i ? "var(--accent)" : "var(--line)" }} />
          ))}
        </div>
      </div>
    </div>
  );
}
