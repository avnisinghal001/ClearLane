import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";

// A single "focused" place, kept in the URL (?lat&lon&h3) so it is deep-linkable
// and shareable. The map turns this into a ripple ("waves out") + numbers peek,
// zooms in, and opens the detail modal when the ripple is tapped.
export interface FocusPoint {
  lat: number;
  lon: number;
  h3?: string;
}

export function useMapFocus() {
  const [sp, setSp] = useSearchParams();

  // Derive from the URL. Memoised on the raw string values so the object identity
  // only changes when the actual coordinates change (stable map effect deps).
  const latStr = sp.get("lat");
  const lonStr = sp.get("lon");
  const h3Str = sp.get("h3");
  const focus = useMemo<FocusPoint | null>(() => {
    const lat = parseFloat(latStr ?? "");
    const lon = parseFloat(lonStr ?? "");
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
    return { lat, lon, h3: h3Str || undefined };
  }, [latStr, lonStr, h3Str]);

  const setFocus = useCallback(
    (f: FocusPoint | null) => {
      setSp(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (f) {
            next.set("lat", f.lat.toFixed(6));
            next.set("lon", f.lon.toFixed(6));
            if (f.h3) next.set("h3", f.h3);
            else next.delete("h3");
          } else {
            next.delete("lat");
            next.delete("lon");
            next.delete("h3");
          }
          return next;
        },
        { replace: false },
      );
    },
    [setSp],
  );

  return { focus, setFocus };
}
