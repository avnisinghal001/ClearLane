import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api.js";

const DEFAULT_W = { A: 50, B: 30, C: 20 };

export default function ValidationPanel() {
  const [d, setD] = useState(null);
  const [zones, setZones] = useState(null);
  const [w, setW] = useState(DEFAULT_W);
  useEffect(() => {
    api("/api/validation").then(setD).catch(console.error);
    api("/api/map/payload").then((p) => setZones(p.zones)).catch(() => {});
  }, []);

  // EXPLORATORY client-side re-rank from the real pillar scores (A/B/C).
  // This is NOT the production ranking — it recomputes a temporary order so you
  // can see how little the top-20 moves as the weights change.
  const reweight = useMemo(() => {
    if (!zones) return null;
    const official = [...zones].sort((a, b) => a.rank - b.rank).slice(0, 20).map((z) => z.id);
    const sum = (w.A + w.B + w.C) || 1;
    const scored = zones.map((z) => ({
      id: z.id, name: z.name,
      p: (w.A * z.pressure + w.B * z.recurrence + w.C * z.emergence) / sum,
    })).sort((a, b) => b.p - a.p);
    const newTop = scored.slice(0, 20).map((z) => z.id);
    const overlap = newTop.filter((id) => official.includes(id)).length;
    return { overlap, isDefault: w.A === DEFAULT_W.A && w.B === DEFAULT_W.B && w.C === DEFAULT_W.C };
  }, [zones, w]);

  if (!d) return <div className="panel">Loading…</div>;

  const v = d.validation;
  const s = v.sensitivity, p = v.persistence, f = v.forecaster || {};
  const shap = f.shap_importance || {};
  const shapMax = Math.max(1, ...Object.values(shap));

  return (
    <div>
      <div className="panel">
        <h2>What we claim — and what we don't</h2>
        <p className="sub">Honesty is the product. Every number here is computed from the dataset or labelled an assumption.</p>
        <div className="note">
          <b>We do NOT measure congestion, flow, speed or delay</b> — the dataset has none. Every row is a
          parking-violation ticket, and ticket <i>times</i> reflect officer shifts, not traffic. We instead
          deliver bias-corrected enforcement intelligence: where chronic structural obstruction is, where
          enforcement is/ isn't working, what will stay hot next month, and the evening enforcement
          blind-spot vs the city's known congestion peaks (an enforcement-coverage gap, stated as such).
        </div>
      </div>

      <div className="grid2">
        <div className="panel">
          <h3>Sensitivity — why these weights?</h3>
          <p className="sub">{s.n_configs} configs, ±{Math.round(s.perturbation * 100)}% on blend + severity/vehicle tables.</p>
          <div className="kv"><span className="k">Top-20 overlap (min–max)</span>
            <span className="mono">{s.top20_overlap_min}–{s.top20_overlap_max}%</span></div>
          <div className="kv"><span className="k">Top-20 overlap (mean)</span><span className="mono">{s.top20_overlap_mean}%</span></div>
          <div className="kv"><span className="k">Top-50 Spearman (mean)</span><span className="mono">{s.top50_spearman_mean}</span></div>
          <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>Perturbing the weights barely moves the ranking — it is not arbitrary.</p>

          <h3 style={{ marginTop: 16 }}>Interactive re-weight <span className="flag">exploratory</span></h3>
          {!reweight ? <p className="muted">loading zones…</p> : (
            <>
              {["A", "B", "C"].map((k) => (
                <div key={k} style={{ marginBottom: 6 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
                    <span>{{ A: "Pressure (A)", B: "Recurrence (B)", C: "Emergence (C)" }[k]}</span>
                    <span className="mono">{w[k]}%</span>
                  </div>
                  <input type="range" min="0" max="100" value={w[k]} className="slider"
                    onChange={(e) => setW({ ...w, [k]: +e.target.value })} />
                </div>
              ))}
              <div className="kv"><span className="k">Top-20 still in official top-20</span>
                <span className="mono"><b>{reweight.overlap}/20</b></span></div>
              <p className="muted" style={{ fontSize: 11 }}>
                This recomputes a <b>temporary client-side</b> ranking from the real pillar scores —
                <b> not the production ranking</b>. Even at extreme weights the top-20 barely moves.
              </p>
              {!reweight.isDefault &&
                <button className="btn" onClick={() => setW(DEFAULT_W)}>Reset to official weights (50/30/20)</button>}
            </>
          )}
        </div>

        <div className="panel">
          <h3>Persistence backtest — are hotspots structural?</h3>
          <p className="sub">Rank on {p.train_months.join("/")}, test on {p.test_months.join("/")}.</p>
          <div className="kv"><span className="k">Spearman (train vs test rank)</span><span className="mono">{p.spearman}</span></div>
          <div className="kv"><span className="k">Top-quartile persistence</span><span className="mono">{p.top_quartile_persistence_pct}%</span></div>
          <div className="kv"><span className="k">Zones backtested</span><span className="mono">{p.n_zones}</span></div>
          <p className="muted" style={{ fontSize: 12, marginTop: 8 }}>Hotspots persist across months — they are real, not noise.</p>
        </div>
      </div>

      <div className="grid2">
        <div className="panel">
          <h3>Forecaster — held-out metrics</h3>
          <p className="sub">{f.model} predicting {f.target}.</p>
          <div className="kv"><span className="k">R²</span><span className="mono">{f.r2}</span></div>
          <div className="kv"><span className="k">Spearman</span><span className="mono">{f.spearman}</span></div>
          <div className="kv"><span className="k">Top-20 precision</span><span className="mono">{f.topk_precision?.top20}</span></div>
          <p className="muted" style={{ fontSize: 11, marginTop: 8 }}>Legitimate because the target is a real
            observed future quantity (violation pressure), never a fabricated congestion label.</p>
        </div>

        <div className="panel">
          <h3>SHAP — what drives predicted future pressure</h3>
          {Object.entries(shap).slice(0, 8).map(([k, val]) => (
            <div key={k} style={{ margin: "5px 0" }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
                <span>{k.replace("feat_", "")}</span><span className="muted mono">{val}</span>
              </div>
              <div className="bar"><span style={{ width: (100 * val / shapMax) + "%" }} /></div>
            </div>
          ))}
          <p className="muted" style={{ fontSize: 11 }}>Method: {f.feature_importance_method}</p>
        </div>
      </div>

      {d.offender_stat && (
        <div className="panel">
          <h3>Habitual-offender headline</h3>
          <p style={{ fontSize: 16 }}><b style={{ color: "#378ADD" }}>{d.offender_stat.pct_tickets_from_repeats}%</b> of
            violations come from just <b style={{ color: "#EF9F27" }}>{d.offender_stat.pct_repeat_vehicles}%</b> of
            vehicles ({d.offender_stat.n_repeat_vehicles.toLocaleString()} of {d.offender_stat.n_vehicles.toLocaleString()}).
            High-repeat zones need parking infrastructure, not just more tickets.</p>
        </div>
      )}
    </div>
  );
}
