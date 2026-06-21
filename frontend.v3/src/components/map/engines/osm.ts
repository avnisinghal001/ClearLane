// Engine 3 — guaranteed final fallback: bundled Leaflet + Carto/OSM raster tiles.
// Always initialises (the map object exists even if tiles can't be fetched), so
// the chain never ends blank. No live traffic on this basemap.
import L from "leaflet";
import "leaflet.heat";
import { createLeafletEngine } from "./leafletEngine";
import type { InitOptions, MapEngine } from "./types";

export async function initOsm(o: InitOptions): Promise<MapEngine> {
  const map = L.map(o.container, { center: o.center, zoom: o.zoom, zoomControl: true, preferCanvas: true });
  L.tileLayer("https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png", {
    maxZoom: 19,
    subdomains: "abcd",
    attribution: "© OpenStreetMap, © CARTO",
  }).addTo(map);
  await new Promise((r) => setTimeout(r, 30));
  return createLeafletEngine({ id: "osm", label: "OSM / Carto", priority: 3, L, map, supportsTraffic: false });
}
