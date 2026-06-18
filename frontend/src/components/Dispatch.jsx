import { useEffect, useState } from "react";
import { QRCodeSVG } from "qrcode.react";
import { api, opDispatch, opFeedback } from "../lib/api.js";
import { tierColor, mapsUrl } from "../lib/format.js";

// each action maps to a real operational feedback kind (closed loop)
const ACTIONS = [
  ["En route", "en_route", "dispatch"],
  ["On site — verify obstruction", "verified_obstruction", "feedback"],
  ["Needs towing", "needs_towing", "feedback"],
  ["Action taken", "action_taken", "feedback"],
  ["Cleared", "cleared", "feedback"],
  ["Structural issue — escalate", "structural_issue", "feedback"],
];

export default function Dispatch({ id, onChange }) {
  const [z, setZ] = useState(null);
  const [status, setStatus] = useState(null);
  const [dispatchId, setDispatchId] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api("/api/zone/" + encodeURIComponent(id)).then(setZ).catch(console.error); }, [id]);
  if (!z) return <div style={{ padding: 24 }}>Loading dispatch…</div>;

  async function run(label, kind, type) {
    setBusy(true);
    try {
      if (type === "dispatch") {
        const d = await opDispatch({ zone_id: z.id, state: "en_route" });
        setDispatchId(d.id);
      } else {
        await opFeedback({ zone_id: z.id, kind, dispatch_id: dispatchId });
      }
      setStatus(label);
      if (onChange) await onChange();
    } finally { setBusy(false); }
  }

  return (
    <div style={{ maxWidth: 480, margin: "0 auto", padding: 18 }}>
      <a href="#/" className="muted" style={{ fontSize: 13 }}>← back to dashboard</a>
      <h1 style={{ margin: "10px 0" }}>{z.name || `Zone ${z.id}`}{" "}
        <span className="tier-pill" style={{ background: tierColor(z.tier) }}>{z.tier}</span></h1>
      <p className="mono muted">{z.lat.toFixed(5)}, {z.lon.toFixed(5)} · zone {z.id}</p>

      <a className="btn accent" style={{ display: "block", textAlign: "center", padding: 16, fontSize: 18 }}
        href={mapsUrl(z.lat, z.lon)} target="_blank" rel="noreferrer">Navigate ↗</a>
      <button className="btn" style={{ width: "100%", marginTop: 8 }}
        onClick={() => navigator.clipboard?.writeText(`${z.lat},${z.lon}`)}>Copy coordinate</button>

      <div style={{ display: "flex", justifyContent: "center", margin: "16px 0" }}>
        <QRCodeSVG value={mapsUrl(z.lat, z.lon)} size={160} bgColor="#0B0E14" fgColor="#E6EAF2" />
      </div>

      <div className="intervention"><b>▸ {z.intervention}</b><br />
        <span className="muted">Window: {z.recommended_window}</span></div>

      <h3>Action checklist</h3>
      <ul style={{ lineHeight: 2 }}>
        <li>Clear obstructing vehicles ({z.vehicle_mix?.[0]?.name || "mixed"})</li>
        <li>{z.habitual ? "Habitual zone — log repeat plates, flag for parking infra" : "Transient — enforcement presence sufficient"}</li>
        <li>{z.evening_blind_spot ? "⚠ Evening blind spot — sweep 17:00–21:00" : "Cover current peak"}</li>
      </ul>

      <h3>Update status (updates the command centre live)</h3>
      <div style={{ display: "grid", gap: 8 }}>
        {ACTIONS.map(([label, kind, type]) => (
          <button key={kind} className={"btn" + (status === label ? " accent" : "")}
            disabled={busy} style={{ padding: 14, fontSize: 15 }}
            onClick={() => run(label, kind, type)}>{label}</button>
        ))}
      </div>
      {status && <p className="note" style={{ marginTop: 12 }}>Reported: <b>{status}</b>. The command-centre
        operational layer has been updated (the historical hotspot stays chronic).</p>}
    </div>
  );
}
