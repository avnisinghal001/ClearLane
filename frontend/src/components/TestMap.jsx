import { useEffect, useRef, useState } from "react";

// Standalone /test page: Mappls Web Maps JS SDK with the live Traffic Visualizer
// (colored congestion lines) over Bengaluru. The Map-SDK key resolves from
// VITE_MAPPLS_KEY first, then falls back to the backend /api/config (so it works
// even when the Vite env wasn't baked into the build).
const ENV_KEY = import.meta.env.VITE_MAPPLS_KEY;
const API_BASE = (import.meta.env.VITE_API_BASE || "").replace(/\/$/, "");
const SDK_ID = "mappls-sdk";
// Aug-2025 Web Maps JS v3.0 endpoint (access_token auth) + {lat,lng} center.
const SDK_URL = (key) =>
  `https://sdk.mappls.com/map/sdk/web?v=3.0&access_token=${encodeURIComponent(key)}`;
const BLR = { lat: 12.9716, lng: 77.5946 };

async function resolveKey() {
  if (ENV_KEY) return ENV_KEY;
  try {                                   // fallback: backend-injected key
    const r = await fetch(`${API_BASE}/api/config`);
    if (r.ok) return (await r.json()).mappls_key || null;
  } catch (e) { /* offline */ }
  return null;
}

export default function TestMap() {
  const mapRef = useRef(null);
  const trafficRef = useRef(null);
  const inited = useRef(false);
  const [status, setStatus] = useState("loading");
  const [keySource, setKeySource] = useState(ENV_KEY ? "env" : null);
  const [traffic, setTraffic] = useState(true);

  useEffect(() => {
    if (inited.current) return;
    inited.current = true;

    const addTraffic = () => {
      try { trafficRef.current = new window.mappls.trafficLayer({ map: mapRef.current, active: true }); }
      catch (e) { /* traffic overlay optional */ }
    };
    const init = () => {
      if (!(window.mappls && window.mappls.Map)) { setStatus("error"); return; }
      try {
        const map = new window.mappls.Map("test-map", {
          center: BLR, zoom: 11, traffic: true,
          zoomControl: true, fullscreenControl: true, location: true, scaleControl: true,
        });
        mapRef.current = map;
        const ready = () => { setStatus("ready"); addTraffic(); };
        if (typeof map.addListener === "function") map.addListener("load", ready);
        else setTimeout(ready, 1000);
      } catch (e) { setStatus("error"); }
    };

    (async () => {
      const key = await resolveKey();
      if (!key) { setStatus("no-key"); return; }
      setKeySource((s) => s || "backend");
      if (window.mappls && window.mappls.Map) { init(); return; }
      let s = document.getElementById(SDK_ID);
      if (!s) {
        s = document.createElement("script");
        s.id = SDK_ID;
        s.src = SDK_URL(key);
        s.async = true;
        document.head.appendChild(s);
      }
      s.addEventListener("load", init);
      s.addEventListener("error", () => setStatus("error"));
    })();
  }, []);

  const toggleTraffic = () => {
    const nx = !traffic; setTraffic(nx);
    const t = trafficRef.current;
    try { if (t && typeof t.remove === "function") { t.remove(); trafficRef.current = null; } } catch (e) {}
    if (nx && mapRef.current) {
      try { trafficRef.current = new window.mappls.trafficLayer({ map: mapRef.current, active: true }); } catch (e) {}
    }
  };

  return (
    <div style={{ position: "fixed", inset: 0, background: "#0b0e14" }}>
      <div id="test-map" style={{ position: "absolute", inset: 0 }} />

      <div style={{
        position: "absolute", top: 12, left: 12, zIndex: 10, display: "flex", gap: 10,
        alignItems: "center", flexWrap: "wrap", background: "rgba(11,14,20,.85)", color: "#fff",
        padding: "9px 13px", borderRadius: 12, backdropFilter: "blur(8px)",
        boxShadow: "0 8px 28px rgba(0,0,0,.4)", fontSize: 13,
      }}>
        <b>Mappls live traffic · Bengaluru</b>
        <button onClick={toggleTraffic} style={{
          cursor: "pointer", border: "1px solid #2b3344", borderRadius: 99, padding: "4px 12px",
          fontWeight: 700, color: traffic ? "#04110d" : "#9aa",
          background: traffic ? "#34d399" : "#161d2b",
        }}>{traffic ? "Traffic: ON" : "Traffic: OFF"}</button>
        <span style={{ opacity: .6 }}>
          {{ loading: "loading SDK…", ready: "live", error: "SDK error", "no-key": "no key" }[status]}
          {status === "ready" && keySource ? ` · key: ${keySource}` : ""}
        </span>
        <a href="#/" style={{ color: "#3AA0FF", textDecoration: "none" }}>← back to app</a>
      </div>

      {status !== "ready" && (
        <div style={{
          position: "absolute", inset: 0, display: "grid", placeItems: "center",
          color: "#9aa6b8", zIndex: 5, textAlign: "center", padding: 24,
        }}>
          {status === "no-key"
            ? "No Mappls key — VITE_MAPPLS_KEY isn't baked in and /api/config returned none. Set MYMAPINDIA_API_KEY on the backend."
            : status === "error"
              ? "Mappls SDK failed to load. Check the key and that this domain is whitelisted in the Mappls console."
              : "Loading Mappls live-traffic map…"}
        </div>
      )}

      <div style={{
        position: "absolute", bottom: 14, left: 12, zIndex: 10, fontSize: 11,
        background: "rgba(11,14,20,.8)", color: "#9aa6b8", padding: "6px 10px", borderRadius: 8,
      }}>
        Green = free-flowing · amber/red = slow/congested (Mappls live traffic). <code>/test</code> sandbox.
      </div>
    </div>
  );
}
