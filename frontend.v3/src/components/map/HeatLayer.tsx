import { useEffect, useRef } from "react";
import { useMap } from "react-leaflet";
import L from "leaflet";
import "leaflet.heat";
import { HEAT_GRADIENT } from "./layers";

// Real-density heatmap via leaflet.heat. Recreated once; points updated in place.
export function HeatLayer({ points, radius = 26, blur = 18 }: { points: [number, number, number][]; radius?: number; blur?: number }) {
  const map = useMap();
  const ref = useRef<L.Layer | null>(null);
  useEffect(() => {
    // @ts-expect-error leaflet.heat augments L at runtime
    ref.current = L.heatLayer(points || [], {
      radius,
      blur,
      max: 1.0,
      minOpacity: 0.32,
      maxZoom: 17,
      gradient: HEAT_GRADIENT,
    }).addTo(map);
    return () => {
      if (ref.current) {
        map.removeLayer(ref.current);
        ref.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map]);
  useEffect(() => {
    // @ts-expect-error runtime method from leaflet.heat
    if (ref.current) ref.current.setLatLngs(points || []);
  }, [points]);
  return null;
}
