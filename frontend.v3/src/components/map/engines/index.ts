// Single ordered provider list + the fallback loader. Try each in priority order,
// stop at the first that fully initialises, and report every attempt so the UI
// can toast the winner (and what it fell back from).
import { initMapmyIndia } from "./mapmyindia";
import { initMappls } from "./mappls";
import { initOsm } from "./osm";
import type { Attempt, InitOptions, InitResult, MapEngine } from "./types";

interface Provider {
  priority: number;
  label: string;
  init: (o: InitOptions) => Promise<MapEngine>;
}

export const PROVIDERS: Provider[] = [
  { priority: 1, label: "MapMyIndia map_load", init: initMapmyIndia },
  { priority: 2, label: "Mappls Web SDK v3.0", init: initMappls },
  { priority: 3, label: "OSM / Carto", init: initOsm },
];

export const PROVIDER_TOTAL = PROVIDERS.length;

// Wipe any partial map state a failed provider left on the container before the
// next attempt (Leaflet stamps `_leaflet_id`; Mappls injects a canvas/DOM).
function resetContainer(el: HTMLElement) {
  try {
    delete (el as unknown as { _leaflet_id?: number })._leaflet_id;
  } catch {
    /* noop */
  }
  el.innerHTML = "";
}

export async function initBestMap(o: InitOptions): Promise<InitResult> {
  const attempts: Attempt[] = [];
  let lastErr: unknown;
  for (const p of PROVIDERS) {
    resetContainer(o.container);
    try {
      const engine = await p.init(o);
      attempts.push({ priority: p.priority, label: p.label, ok: true });
      return { engine, attempts };
    } catch (e) {
      attempts.push({ priority: p.priority, label: p.label, ok: false, error: e instanceof Error ? e.message : String(e) });
      lastErr = e;
    }
  }
  throw lastErr instanceof Error ? lastErr : new Error("All map providers failed");
}

export type { MapEngine } from "./types";
