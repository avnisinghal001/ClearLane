// Engine 2 — Mappls Web SDK v3.0 (native WebGL vector). Different API from
// Leaflet, so this implements the adapter directly. Defensive throughout: if the
// SDK or a required class is missing the init throws and the chain falls through
// to engine 3.
import { loadScriptOnce, type CircleSpec, type HeatPoint, type InitOptions, type MapEngine, type PinSpec, type PolylineSpec } from "./types";

/* eslint-disable @typescript-eslint/no-explicit-any */

const w = () => window as any;
const MAX_CIRCLES = 300; // DOM markers are heavy; cap on this fallback engine

function circleHtml(c: CircleSpec) {
  const d = Math.round(c.radius * 2);
  return `<div style="width:${d}px;height:${d}px;border-radius:50%;background:${c.fillColor};opacity:.62;border:${c.weight}px solid ${c.color}"></div>`;
}
function pinHtml(p: PinSpec) {
  if (p.kind === "user")
    return `<div class="cl-pulse" style="width:16px;height:16px;border-radius:50%;background:#2563eb;border:3px solid #fff"></div>`;
  if (p.kind === "num")
    return `<div style="min-width:20px;height:20px;padding:0 4px;border-radius:10px;background:${p.color};color:#fff;font:700 11px/20px Inter;text-align:center;border:2px solid #fff">${p.num ?? 0}</div>`;
  return `<div class="cl-pin ${p.pulse ? "cl-pulse" : ""}" style="width:18px;height:18px;border-radius:50% 50% 50% 0;transform:rotate(-45deg);background:${p.color};border:2px solid #fff"></div>`;
}

export async function initMappls(o: InitOptions): Promise<MapEngine> {
  const key = o.staticKey || o.restKey;
  if (!key) throw new Error("no Mappls key");
  await loadScriptOnce(`https://sdk.mappls.com/map/sdk/web?v=3.0&access_token=${key}`, "mappls-v3", 6000);

  const mappls = w().mappls;
  if (!mappls || typeof mappls.Map !== "function" || typeof mappls.Marker !== "function") {
    throw new Error("Mappls v3 SDK unavailable");
  }

  const map = new mappls.Map(o.container, { center: o.center, zoom: o.zoom, zoomControl: true, location: true });

  // require the map to actually finish loading, else clean up + fall through
  await new Promise<void>((resolve, reject) => {
    const to = setTimeout(() => {
      try {
        map.remove?.();
      } catch {
        /* noop */
      }
      reject(new Error("Mappls load timeout"));
    }, 6000);
    const done = () => {
      clearTimeout(to);
      resolve();
    };
    try {
      if (typeof map.addListener === "function") map.addListener("load", done);
      else if (typeof map.on === "function") map.on("load", done);
      else setTimeout(done, 400);
    } catch {
      setTimeout(done, 400);
    }
  });

  let circles: any[] = [];
  let pins: any[] = [];
  let lines: any[] = [];
  let heat: any = null;

  const removeAll = (arr: any[]) => {
    for (const obj of arr) {
      try {
        if (typeof obj.remove === "function") obj.remove();
        else mappls.remove({ map, layer: obj });
      } catch {
        /* noop */
      }
    }
  };

  return {
    id: "mappls",
    label: "Mappls Web SDK v3.0",
    priority: 2,
    supportsTraffic: true,
    setView(center, zoom) {
      try {
        map.setView ? map.setView(center, zoom) : map.flyTo?.({ center, zoom });
      } catch {
        /* noop */
      }
    },
    getZoom() {
      try {
        return map.getZoom?.() ?? o.zoom;
      } catch {
        return o.zoom;
      }
    },
    onMapClick(cb) {
      const handler = (e: any) => {
        const ll = e?.lngLat ?? e?.latLng ?? e?.latlng;
        const lat = ll?.lat ?? (Array.isArray(ll) ? ll[1] : undefined);
        const lng = ll?.lng ?? (Array.isArray(ll) ? ll[0] : undefined);
        if (lat != null && lng != null) cb(lat, lng);
      };
      try {
        if (typeof map.addListener === "function") map.addListener("click", handler);
        else map.on?.("click", handler);
      } catch {
        /* noop */
      }
    },
    setCircles(specs: CircleSpec[]) {
      removeAll(circles);
      circles = [];
      for (const c of specs.slice(0, MAX_CIRCLES)) {
        try {
          const m = new mappls.Marker({
            map,
            position: { lat: c.lat, lng: c.lon },
            html: circleHtml(c),
            width: Math.round(c.radius * 2),
            height: Math.round(c.radius * 2),
            popupHtml: c.tooltip,
            fitbounds: false,
          });
          if (c.onClick && typeof m.addListener === "function") m.addListener("click", c.onClick);
          circles.push(m);
        } catch {
          /* skip */
        }
      }
    },
    setHeat(points: HeatPoint[], on: boolean) {
      try {
        if (heat) {
          mappls.remove({ map, layer: heat });
          heat = null;
        }
        if (on && points.length && typeof mappls.HeatmapLayer === "function") {
          heat = new mappls.HeatmapLayer({
            map,
            data: {
              type: "FeatureCollection",
              features: points.map((p) => ({
                type: "Feature",
                properties: { weight: p.intensity },
                geometry: { type: "Point", coordinates: [p.lon, p.lat] },
              })),
            },
          });
        }
      } catch {
        /* heat unavailable */
      }
    },
    setPins(specs: PinSpec[]) {
      removeAll(pins);
      pins = [];
      for (const p of specs) {
        try {
          const m = new mappls.Marker({ map, position: { lat: p.lat, lng: p.lon }, html: pinHtml(p), popupHtml: p.popup, fitbounds: false });
          if (p.onClick && typeof m.addListener === "function") m.addListener("click", p.onClick);
          pins.push(m);
        } catch {
          /* skip */
        }
      }
    },
    setPolylines(specs: PolylineSpec[]) {
      removeAll(lines);
      lines = [];
      if (typeof mappls.Polyline !== "function") return;
      for (const ln of specs) {
        if (ln.points.length < 2) continue;
        try {
          const pl = new mappls.Polyline({
            map,
            path: ln.points.map(([lat, lng]) => ({ lat, lng })),
            strokeColor: ln.color,
            strokeWidth: 3,
          });
          lines.push(pl);
        } catch {
          /* skip */
        }
      }
    },
    setTraffic(on: boolean) {
      try {
        if (typeof map.setTraffic === "function") map.setTraffic(on);
        else if (typeof map.trafficLayer === "function") map.trafficLayer(on);
      } catch {
        /* noop */
      }
    },
    invalidate() {
      try {
        map.resize?.();
      } catch {
        /* noop */
      }
    },
    destroy() {
      try {
        removeAll(circles);
        removeAll(pins);
        removeAll(lines);
        map.remove?.();
      } catch {
        /* noop */
      }
    },
  };
}
