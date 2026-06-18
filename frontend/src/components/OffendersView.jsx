import { useEffect, useMemo, useState } from "react";
import { MapContainer, TileLayer, CircleMarker, Popup } from "react-leaflet";
import { api } from "../lib/api.js";

// Repeat-vehicle tracing. Which anonymized vehicle keeps offending, where and when.
// HONESTY: vehicle_number is anonymized & stable — NO real identities. Zones where
// the same vehicles return daily usually need parking infrastructure, not just
// more tickets (a structural-demand signal, not a person).
const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso.replace(" ", "T"));
  return d.toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
}
function fmtTime(iso) {
  if (!iso) return "";
  const d = new Date(iso.replace(" ", "T"));
  return d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false });
}

export default function OffendersView({ onSelect }) {
  const [data, setData] = useState(null);
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(null);
  const [sort, setSort] = useState("n_tickets");

  useEffect(() => {
    api("/api/offenders").then((d) => {
      setData(d);
      if (d?.vehicles?.length) setSel(d.vehicles[0].vehicle);
    }).catch(() => setData({ vehicles: [], summary: {} }));
  }, []);

  const list = useMemo(() => {
    if (!data) return [];
    const ql = q.toLowerCase();
    let r = data.vehicles;
    if (ql) r = r.filter((v) =>
      v.vehicle.toLowerCase().includes(ql) ||
      (v.vehicle_type || "").toLowerCase().includes(ql) ||
      v.top_zones.some((z) => (z.name || "").toLowerCase().includes(ql)));
    return [...r].sort((a, b) => (b[sort] ?? 0) - (a[sort] ?? 0));
  }, [data, q, sort]);

  const veh = useMemo(
    () => data?.vehicles.find((v) => v.vehicle === sel) || null, [data, sel]);

  if (!data) return <div className="panel">Loading repeat-offender logs…</div>;
  const s = data.summary || {};

  return (
    <div className="panel">
      <h2>Repeat-vehicle tracing</h2>
      <p className="sub">
        The most-ticketed vehicles, each with a time-wise log of where & when.
        {s.pct_tickets_from_repeats != null && <> Citywide, <b>{s.pct_tickets_from_repeats}% of
          tickets come from {s.pct_repeat_vehicles}% of vehicles.</b></>}{" "}
        Vehicle IDs are <b>anonymized & stable — no real identities</b>. Zones the
        same vehicles return to need parking infrastructure, not just more tickets.
      </p>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(240px, 320px) 1fr", gap: 16, minHeight: 0 }}>
        {/* ---- vehicle list ------------------------------------------------ */}
        <div style={{ minWidth: 0 }}>
          <input className="searchbox" style={{ width: "100%", marginBottom: 6 }}
            placeholder="Search vehicle / type / zone…" value={q}
            onChange={(e) => setQ(e.target.value)} />
          <div style={{ display: "flex", gap: 6, marginBottom: 6, fontSize: 11 }}>
            <span className="muted">sort:</span>
            {[["n_tickets", "tickets"], ["n_zones", "zones"]].map(([k, l]) => (
              <button key={k} className={"btn" + (sort === k ? " accent" : "")}
                style={{ fontSize: 11, padding: "1px 8px" }} onClick={() => setSort(k)}>{l}</button>
            ))}
          </div>
          <div className="scroll" style={{ maxHeight: "62vh" }}>
            {list.map((v) => (
              <div key={v.vehicle} onClick={() => setSel(v.vehicle)}
                style={{
                  padding: "8px 10px", marginBottom: 5, borderRadius: 6, cursor: "pointer",
                  background: v.vehicle === sel ? "rgba(55,138,221,0.16)" : "var(--panel2, #161b27)",
                  border: v.vehicle === sel ? "1px solid var(--accent)" : "1px solid transparent",
                }}>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <b className="mono" style={{ fontSize: 12 }}>{v.vehicle}</b>
                  <span className="mono" style={{ color: "var(--accent)" }}>{v.n_tickets}×</span>
                </div>
                <div className="muted" style={{ fontSize: 11 }}>
                  {v.vehicle_type || "—"} · {v.n_zones} zone{v.n_zones > 1 ? "s" : ""} · last {fmtDate(v.last)}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* ---- selected vehicle detail ------------------------------------ */}
        {veh && (
          <div style={{ minWidth: 0 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", flexWrap: "wrap", gap: 8 }}>
              <h3 className="mono" style={{ margin: 0 }}>{veh.vehicle}</h3>
              <span className="muted" style={{ fontSize: 12 }}>
                {veh.vehicle_type || "—"} · peak hour {String(veh.peak_hour).padStart(2, "0")}:00</span>
            </div>

            <div className="dials" style={{ margin: "8px 0" }}>
              <div className="dial"><div className="v">{veh.n_tickets}</div><div className="l">Tickets</div></div>
              <div className="dial"><div className="v">{veh.n_zones}</div><div className="l">Distinct zones</div></div>
              <div className="dial"><div className="v" style={{ fontSize: 14 }}>{fmtDate(veh.first)}</div><div className="l">First seen</div></div>
              <div className="dial"><div className="v" style={{ fontSize: 14 }}>{fmtDate(veh.last)}</div><div className="l">Last seen</div></div>
            </div>

            <div className="note" style={{ margin: "6px 0" }}>
              {veh.n_zones === 1
                ? "⚠ Same spot every time — a structural-demand signal. This location needs a physical fix (bollard / No-Parking board / designated parking), not just repeat tickets."
                : `Roams across ${veh.n_zones} zones — a mobile repeat offender. Escalate via the towing / fine-recovery process.`}
            </div>

            <div style={{ margin: "8px 0" }}>
              <span className="muted" style={{ fontSize: 11 }}>Repeats most at: </span>
              {veh.top_zones.map((z) => (
                <span key={z.id} className="tag tran" style={{ cursor: "pointer" }}
                  onClick={() => onSelect(z.id)}>{z.name} · {z.n}×</span>
              ))}
            </div>

            {/* mini-map of this vehicle's ticket points */}
            <div style={{ height: 220, borderRadius: 8, overflow: "hidden", margin: "8px 0" }}>
              <MapContainer key={veh.vehicle}
                center={[veh.timeline[0]?.lat || 12.97, veh.timeline[0]?.lon || 77.59]}
                zoom={12} preferCanvas style={{ height: "100%" }}>
                <TileLayer url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
                  attribution="© OpenStreetMap, © CARTO" />
                {veh.timeline.map((t, i) => (
                  <CircleMarker key={i} center={[t.lat, t.lon]} radius={5}
                    pathOptions={{ color: "#EF9F27", weight: 1, fillColor: "#EF9F27", fillOpacity: 0.55 }}>
                    <Popup><b>{t.zn}</b><br />{fmtDate(t.t)} {fmtTime(t.t)}<br />{t.v}</Popup>
                  </CircleMarker>
                ))}
              </MapContainer>
            </div>

            {/* time-wise log */}
            <h3 style={{ marginTop: 10 }}>Time-wise log
              <span className="muted" style={{ fontSize: 11, fontWeight: 400 }}>
                {veh.n_tickets > (data.timeline_cap || 60) ? ` (most recent ${data.timeline_cap})` : ""}</span></h3>
            <div className="scroll" style={{ maxHeight: "34vh" }}>
              {[...veh.timeline].reverse().map((t, i) => (
                <div key={i} onClick={() => onSelect(t.z)}
                  style={{ display: "grid", gridTemplateColumns: "92px 1fr auto", gap: 8, padding: "6px 8px",
                    borderBottom: "1px solid rgba(255,255,255,0.05)", cursor: "pointer", fontSize: 12 }}>
                  <span className="mono muted">{fmtDate(t.t)} {fmtTime(t.t)}</span>
                  <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}><b>{t.zn}</b></span>
                  <span className="muted" style={{ fontSize: 11 }}>{t.v}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
