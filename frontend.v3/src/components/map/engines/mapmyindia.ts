// Engine 1 — MapMyIndia "map_load" v1.5 (Leaflet-based), per c:\ClearLane\h.html.
// Injects the script for a key, then `new MapmyIndia.Map(divId, …)` and drives
// every overlay through the GLOBAL Leaflet `L` the script exposes.
import { createLeafletEngine } from "./leafletEngine";
import { loadScriptOnce, type InitOptions, type MapEngine } from "./types";

/* eslint-disable @typescript-eslint/no-explicit-any */

const w = () => window as any;

async function loadForKey(key: string): Promise<void> {
  // `plugins=heatmap` gives us global L.heatLayer for the heatmap toggle.
  await loadScriptOnce(
    `https://apis.mapmyindia.com/advancedmaps/v1/${key}/map_load?v=1.5&plugins=heatmap`,
    `mmi-${key.slice(0, 6)}`,
  );
  // The script must have populated the MapmyIndia + L globals.
  if (!w().MapmyIndia || !w().L) throw new Error("MapMyIndia globals missing");
}

export async function initMapmyIndia(o: InitOptions): Promise<MapEngine> {
  const keys = Array.from(new Set([o.restKey, o.staticKey].filter(Boolean))) as string[];
  if (!keys.length) throw new Error("no MapMyIndia key");

  let loaded = false;
  let lastErr: unknown;
  for (const key of keys) {
    try {
      await loadForKey(key);
      loaded = true;
      break;
    } catch (e) {
      lastErr = e;
    }
  }
  if (!loaded) throw lastErr instanceof Error ? lastErr : new Error("MapMyIndia load failed");

  const L = w().L;
  const MapmyIndia = w().MapmyIndia;
  if (!o.container.id) o.container.id = "mmi-map-" + Math.random().toString(36).slice(2);

  const created = new MapmyIndia.Map(o.container.id, {
    center: o.center,
    zoom: o.zoom,
    zoomControl: true,
    search: true, // built-in search box
    location: true, // built-in "locate me" control (tracks user + recenters)
    hybrid: false,
  });
  const map = created && typeof created.setView === "function" ? created : created?.map;
  if (!map || typeof map.setView !== "function") throw new Error("MapmyIndia.Map did not return a Leaflet map");

  await new Promise((r) => setTimeout(r, 80));

  return createLeafletEngine({
    id: "mapmyindia",
    label: "MapMyIndia map_load",
    priority: 1,
    L,
    map,
    supportsTraffic: true,
    makeTraffic: () => {
      // Best-effort live-traffic layer from the plugin (varies by key/plan).
      try {
        if (typeof MapmyIndia.trafficLayer === "function") return MapmyIndia.trafficLayer();
      } catch {
        /* noop */
      }
      try {
        if (typeof (L as any).trafficLayer === "function") return (L as any).trafficLayer();
      } catch {
        /* noop */
      }
      return null;
    },
  });
}
