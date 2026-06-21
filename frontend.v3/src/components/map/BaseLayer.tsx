import { useEffect } from "react";
import { useMap } from "react-leaflet";
import L from "leaflet";
import { buildMapmyIndiaBase, loadMapmyIndia } from "./mapmyindia";

export type BaseKind = "mappls" | "light" | "osm";

const TILES: Record<Exclude<BaseKind, "mappls"> | "voyager", { url: string; attribution: string }> = {
  voyager: {
    url: "https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png",
    attribution: "© OpenStreetMap, © CARTO",
  },
  light: {
    url: "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
    attribution: "© OpenStreetMap, © CARTO",
  },
  osm: {
    url: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    attribution: "© OpenStreetMap",
  },
};

// Imperative base-layer manager: full control over the Mappls→Carto fallback so
// the map ALWAYS has tiles even when the domain-whitelisted Mappls key fails.
export function BaseLayer({
  base,
  mapKey,
  onResolved,
}: {
  base: BaseKind;
  mapKey: string | null;
  onResolved?: (which: "mappls" | "carto") => void;
}) {
  const map = useMap();
  useEffect(() => {
    let current: L.Layer | null = null;
    let cancelled = false;

    const addCarto = (k: "voyager" | "light" | "osm") => {
      const t = TILES[k];
      current = L.tileLayer(t.url, { maxZoom: 19, attribution: t.attribution, subdomains: "abcd" });
      current.addTo(map);
    };

    if (base === "osm") {
      addCarto("osm");
    } else if (base === "light") {
      addCarto("light");
      onResolved?.("carto");
    } else {
      // Mappls: render Voyager immediately, swap to Mappls tiles if the plugin loads.
      addCarto("voyager");
      if (mapKey) {
        loadMapmyIndia(mapKey)
          .then((MM) => {
            if (cancelled || !MM) return onResolved?.("carto");
            const layer = buildMapmyIndiaBase(MM);
            if (layer) {
              layer.addTo(map);
              if (current) map.removeLayer(current);
              current = layer;
              onResolved?.("mappls");
            } else {
              onResolved?.("carto");
            }
          })
          .catch(() => !cancelled && onResolved?.("carto"));
      } else {
        onResolved?.("carto");
      }
    }

    return () => {
      cancelled = true;
      if (current) map.removeLayer(current);
    };
  }, [base, mapKey, map, onResolved]);

  return null;
}
