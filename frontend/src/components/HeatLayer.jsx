import { useEffect, useRef } from "react";
import { useMap } from "react-leaflet";
import L from "leaflet";
import "leaflet.heat";

// Shared real-density heatmap (leaflet.heat) used on every map. Vivid, legible
// ramp: blue -> cyan -> green -> yellow -> orange -> red.
export const HEAT_GRADIENT = {
  0.2: "#1f6feb", 0.4: "#22d3ee", 0.55: "#34d399",
  0.72: "#fde047", 0.86: "#fb923c", 1.0: "#ef4444",
};

// PS1 metrics: parking-violation hotspot density + their flow/congestion impact.
export const HEAT_METRICS = {
  pressure: { label: "Obstruction pressure — parking hotspots", field: "pressure" },
  flow_impact: { label: "Flow / congestion impact (CII)", field: "flow_impact" },
  forecast_score: { label: "Forecast — next-month pressure", field: "forecast_score" },
  under_observed: { label: "Blind spots — under-observed", field: "under_observed" },
};

export function heatPoints(zones, metric = "pressure") {
  const field = (HEAT_METRICS[metric] || HEAT_METRICS.pressure).field;
  return (zones || [])
    .filter((z) => z && z.lat != null && z.lon != null)
    .map((z) => [z.lat, z.lon, Math.max(0.05, Math.min(1, (z[field] ?? z.pressure ?? 0) / 100))]);
}

export function HeatLayer({ points, radius = 28, blur = 20 }) {
  const map = useMap();
  const ref = useRef(null);
  useEffect(() => {
    ref.current = L.heatLayer(points || [], {
      radius, blur, max: 1.0, minOpacity: 0.35, maxZoom: 17, gradient: HEAT_GRADIENT,
    }).addTo(map);
    return () => { if (ref.current) { map.removeLayer(ref.current); ref.current = null; } };
  }, [map]);                                   // create once
  useEffect(() => { if (ref.current) ref.current.setLatLngs(points || []); }, [points]);
  return null;
}

// Floating on/off switch (feature-flag style) + optional metric picker. Place it
// inside a position:relative map wrapper.
export function HeatToggle({ on, onToggle, metric, setMetric, pos = "tr", label = "Heatmap" }) {
  return (
    <div className={"heat-toggle heat-" + pos}>
      <label className="heat-switch" title="Toggle density heatmap">
        <input type="checkbox" checked={on} onChange={(e) => onToggle(e.target.checked)} />
        <span className="hs-track"><span className="hs-thumb" /></span>
        <span className="hs-label">{label}</span>
      </label>
      {on && setMetric && (
        <select className="heat-metric" value={metric} onChange={(e) => setMetric(e.target.value)}>
          {Object.entries(HEAT_METRICS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </select>
      )}
      {on && <div className="heat-ramp" title="low → high" />}
    </div>
  );
}
