import { useEffect } from "react";
import { useMap } from "react-leaflet";
import L from "leaflet";
import { buildMapmyIndiaTraffic, loadMapmyIndia } from "./mapmyindia";

// Live-traffic overlay from the Mappls plugin. Live data only — if the plugin or
// key is unavailable we report it (never fake traffic from ticket data).
export function TrafficLayer({
  mapKey,
  onStatus,
}: {
  mapKey: string | null;
  onStatus?: (s: "on" | "unavailable") => void;
}) {
  const map = useMap();
  useEffect(() => {
    let layer: L.Layer | null = null;
    let cancelled = false;
    if (!mapKey) {
      onStatus?.("unavailable");
      return;
    }
    loadMapmyIndia(mapKey)
      .then((MM) => {
        if (cancelled) return;
        const t = buildMapmyIndiaTraffic(MM);
        if (t) {
          t.addTo(map);
          layer = t;
          onStatus?.("on");
        } else {
          onStatus?.("unavailable");
        }
      })
      .catch(() => !cancelled && onStatus?.("unavailable"));
    return () => {
      cancelled = true;
      if (layer) map.removeLayer(layer);
    };
  }, [map, mapKey, onStatus]);
  return null;
}
