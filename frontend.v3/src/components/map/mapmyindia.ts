import L from "leaflet";

// Loads the MapmyIndia/Mappls advancedmaps "map_load" plugin once. The script is
// tied to a domain-whitelisted key, so it may fail (localhost / quota); callers
// must fall back to Carto/OSM tiles.
let _promise: Promise<unknown> | null = null;

export function loadMapmyIndia(key: string): Promise<unknown> {
  if (typeof window === "undefined") return Promise.reject(new Error("no window"));
  const w = window as unknown as { MapmyIndia?: unknown };
  if (w.MapmyIndia) return Promise.resolve(w.MapmyIndia);
  if (_promise) return _promise;
  _promise = new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = `https://apis.mapmyindia.com/advancedmaps/v1/${key}/map_load?v=1.5&vectorLayer`;
    s.async = true;
    s.onload = () => resolve((window as unknown as { MapmyIndia?: unknown }).MapmyIndia ?? null);
    s.onerror = () => {
      _promise = null;
      reject(new Error("mappls script failed to load"));
    };
    document.head.appendChild(s);
  });
  return _promise;
}

// Best-effort: turn whatever MapmyIndia.tiles() returns (a layer, an array, or a
// URL template) into a Leaflet base layer. Returns null if nothing usable.
export function buildMapmyIndiaBase(MM: unknown): L.Layer | null {
  const mm = MM as { tiles?: () => unknown };
  try {
    if (mm && typeof mm.tiles === "function") {
      const t = mm.tiles();
      if (t instanceof L.Layer) return t;
      if (Array.isArray(t) && t.length) {
        if (t[0] instanceof L.Layer) return t[0] as L.Layer;
        if (typeof t[0] === "string") return L.tileLayer(t[0], { maxZoom: 18, attribution: "© Mappls" });
      }
      if (typeof t === "string") return L.tileLayer(t, { maxZoom: 18, attribution: "© Mappls" });
    }
  } catch {
    /* fall through */
  }
  return null;
}

// Best-effort live-traffic overlay from the Mappls plugin.
export function buildMapmyIndiaTraffic(MM: unknown): L.Layer | null {
  const mm = MM as { trafficLayer?: () => unknown; traffic?: () => unknown };
  try {
    const fn = mm?.trafficLayer ?? mm?.traffic;
    if (typeof fn === "function") {
      const t = fn.call(mm);
      if (t instanceof L.Layer) return t;
      if (typeof t === "string") return L.tileLayer(t, { maxZoom: 18, opacity: 0.9 });
    }
  } catch {
    /* fall through */
  }
  return null;
}
