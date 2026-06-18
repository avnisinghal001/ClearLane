import { useMemo, useState } from "react";
import { tierColor } from "../lib/format.js";

export default function PriorityTable({ zones, onSelect, opByZone = {} }) {
  const [sort, setSort] = useState("rank");
  const [dir, setDir] = useState(1);
  const [tier, setTier] = useState("");

  const rows = useMemo(() => {
    let r = tier ? zones.filter((z) => z.tier === tier) : zones;
    return [...r].sort((a, b) => {
      const x = a[sort], y = b[sort];
      if (typeof x === "string") return dir * x.localeCompare(y);
      return dir * ((x ?? 0) - (y ?? 0));
    });
  }, [zones, sort, dir, tier]);

  const head = (key, label) => (
    <th onClick={() => { setSort(key); setDir(sort === key ? -dir : 1); }}>
      {label}{sort === key ? (dir > 0 ? " ▲" : " ▼") : ""}</th>
  );

  return (
    <div className="panel">
      <h2>Deployment priority queue</h2>
      <p className="sub">Ranked by Operational Priority (0.5·pressure + 0.3·recurrence + 0.2·emergence).
        Bias-adjusted rank corrects for enforcement exposure. Click a row to inspect.</p>
      <div style={{ marginBottom: 10 }}>
        {["", "P1", "P2", "P3", "P4"].map((t) => (
          <button key={t || "all"} className={"btn" + (tier === t ? " accent" : "")}
            style={{ marginRight: 6 }} onClick={() => setTier(t)}>{t || "All"}</button>
        ))}
      </div>
      <div className="scroll">
        <table>
          <thead>
            <tr>
              {head("rank", "#")}<th>Location</th>{head("tier", "Tier")}{head("priority", "Priority")}
              {head("pressure", "Pressure")}{head("recurrence", "Recurrence")}
              {head("bias_adjusted_rank", "Bias-adj #")}<th>Flags</th>
              <th>Station</th><th>Coords</th><th>Recommended intervention</th>
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, 400).map((z) => (
              <tr key={z.id} onClick={() => onSelect(z.id)}>
                <td className="mono">{z.rank}</td>
                <td><b>{z.name}</b><span className="mono muted" style={{ fontSize: 10 }}> {z.id}</span></td>
                <td><span className="tier-pill" style={{ background: tierColor(z.tier) }}>{z.tier}</span></td>
                <td>{z.priority}</td><td>{z.pressure}</td><td>{z.recurrence}</td>
                <td className="mono">{z.bias_adjusted_rank}
                  {z.under_recognized && <span title="under-recognized vs patrol exposure"> ↑</span>}</td>
                <td>
                  {opByZone[z.id] && <span className="flag bs" title="live operational activity">⚑ ops</span>}
                  {z.evening_blind_spot && <span className="flag bs">blind</span>}
                  {z.emerging && <span className="flag em">emerging</span>}
                  {z.forecast_rising && <span className="flag rise">rising</span>}
                  {z.habitual && <span className="flag">habitual</span>}
                </td>
                <td>{z.station || "—"}</td>
                <td className="mono" style={{ fontSize: 11 }}>{z.lat.toFixed(4)},{z.lon.toFixed(4)}</td>
                <td style={{ fontSize: 12 }}>{z.intervention}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
