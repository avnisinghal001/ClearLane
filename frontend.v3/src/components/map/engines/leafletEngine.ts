// Shared Leaflet adapter — powers BOTH engine 1 (MapMyIndia map_load, using the
// global `L` the script exposes) and engine 3 (bundled Leaflet + OSM/Carto). The
// only difference is which `L` instance and map are passed in.
import { HEAT_GRADIENT, type CircleSpec, type DotSpec, type EngineId, type HeatPoint, type MapEngine, type PinSpec, type PolylineSpec, type RingSpec } from "./types";

/* eslint-disable @typescript-eslint/no-explicit-any */

function pinHtml(color: string, pulse?: boolean) {
  return `<div class="cl-pin ${pulse ? "cl-pulse" : ""}" style="width:18px;height:18px;border-radius:50% 50% 50% 0;transform:rotate(-45deg);background:${color};border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.4)"></div>`;
}
function numHtml(n: number, color: string) {
  return `<div style="min-width:20px;height:20px;padding:0 4px;border-radius:10px;background:${color};color:#fff;font:700 11px/20px Inter,sans-serif;text-align:center;border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.4)">${n}</div>`;
}
function userHtml() {
  return `<div class="cl-pulse" style="width:16px;height:16px;border-radius:50%;background:#2563eb;border:3px solid #fff;box-shadow:0 0 0 2px #2563eb55"></div>`;
}

export interface LeafletEngineConfig {
  id: EngineId;
  label: string;
  priority: number;
  L: any;
  map: any;
  supportsTraffic: boolean;
  makeTraffic?: () => any | null;
}

export function createLeafletEngine(cfg: LeafletEngineConfig): MapEngine {
  const { L, map } = cfg;
  // Shared CANVAS renderer so the full ~6.5k-cell occupied set renders smoothly
  // (SVG would choke). MapMyIndia's Leaflet map defaults to SVG, so we force a
  // canvas renderer per overlay layer here.
  let canvasRenderer: any = null;
  try {
    canvasRenderer = typeof L.canvas === "function" ? L.canvas({ padding: 0.5 }) : null;
  } catch {
    canvasRenderer = null;
  }
  const withRenderer = (opts: any) => (canvasRenderer ? { ...opts, renderer: canvasRenderer } : opts);
  const dotLayer = L.layerGroup().addTo(map); // evidence points (bottom)
  const circleLayer = L.layerGroup().addTo(map);
  const ringLayer = L.layerGroup().addTo(map); // blind-spot rings (above circles)
  const pinLayer = L.layerGroup().addTo(map);
  const lineLayer = L.layerGroup().addTo(map);
  let heat: any = null;
  let traffic: any = null;

  function icon(p: PinSpec) {
    const html = p.kind === "user" ? userHtml() : p.kind === "num" ? numHtml(p.num ?? 0, p.color) : pinHtml(p.color, p.pulse);
    const anchor = p.kind === "pin" ? [9, 18] : p.kind === "num" ? [10, 10] : [8, 8];
    return L.divIcon({ className: "", html, iconSize: [18, 18], iconAnchor: anchor, popupAnchor: [0, -16] });
  }

  return {
    id: cfg.id,
    label: cfg.label,
    priority: cfg.priority,
    supportsTraffic: cfg.supportsTraffic,
    setView(center, zoom, animate = true) {
      map.setView(center, zoom, { animate });
    },
    getZoom() {
      return map.getZoom();
    },
    onMapClick(cb) {
      map.on("click", (e: any) => cb(e.latlng.lat, e.latlng.lng));
    },
    setCircles(circles: CircleSpec[]) {
      circleLayer.clearLayers();
      for (const c of circles) {
        const m = L.circleMarker([c.lat, c.lon], withRenderer({
          radius: c.radius,
          color: c.color,
          weight: c.weight,
          fillColor: c.fillColor,
          fillOpacity: 0.62,
        }));
        if (c.tooltip) m.bindTooltip(c.tooltip, { direction: "top", offset: [0, -2] });
        if (c.onClick) m.on("click", c.onClick);
        m.addTo(circleLayer);
      }
    },
    setHeat(points: HeatPoint[], on: boolean) {
      if (heat) {
        map.removeLayer(heat);
        heat = null;
      }
      if (on && points.length && typeof L.heatLayer === "function") {
        heat = L.heatLayer(
          points.map((p) => [p.lat, p.lon, p.intensity]),
          { radius: 26, blur: 18, max: 1, minOpacity: 0.32, maxZoom: 17, gradient: HEAT_GRADIENT },
        ).addTo(map);
      }
    },
    setPins(pins: PinSpec[]) {
      pinLayer.clearLayers();
      for (const p of pins) {
        const m = L.marker([p.lat, p.lon], { icon: icon(p), zIndexOffset: p.kind === "user" ? 1000 : 0 });
        if (p.popup) m.bindPopup(p.popup);
        if (p.onClick) m.on("click", p.onClick);
        m.addTo(pinLayer);
      }
    },
    setPolylines(lines: PolylineSpec[]) {
      lineLayer.clearLayers();
      for (const ln of lines) {
        if (ln.points.length < 2) continue;
        L.polyline(ln.points, { color: ln.color, weight: 3, opacity: 0.85, dashArray: "6 4" }).addTo(lineLayer);
      }
    },
    setRings(rings: RingSpec[]) {
      ringLayer.clearLayers();
      for (const r of rings) {
        const m = L.circleMarker([r.lat, r.lon], withRenderer({
          radius: r.radius,
          color: r.color,
          weight: r.weight ?? 1.4,
          dashArray: r.dashArray ?? "4",
          fill: false,
        }));
        if (r.tooltip) m.bindTooltip(r.tooltip, { direction: "top", offset: [0, -2] });
        m.addTo(ringLayer);
      }
    },
    setDots(dots: DotSpec[]) {
      dotLayer.clearLayers();
      for (const d of dots) {
        L.circleMarker([d.lat, d.lon], withRenderer({
          radius: d.radius ?? 1.7,
          color: d.color ?? "#64748b",
          weight: 0,
          fillColor: d.color ?? "#64748b",
          fillOpacity: 0.5,
          interactive: false,
        })).addTo(dotLayer);
      }
    },
    setTraffic(on: boolean) {
      if (traffic) {
        try {
          map.removeLayer(traffic);
        } catch {
          /* noop */
        }
        traffic = null;
      }
      if (on && cfg.makeTraffic) {
        try {
          const t = cfg.makeTraffic();
          if (t) {
            t.addTo(map);
            traffic = t;
          }
        } catch {
          /* traffic unavailable — leave off */
        }
      }
    },
    invalidate() {
      try {
        map.invalidateSize();
      } catch {
        /* noop */
      }
    },
    destroy() {
      try {
        map.remove();
      } catch {
        /* noop */
      }
    },
  };
}
