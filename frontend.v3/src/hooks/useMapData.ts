import { useCallback, useEffect, useRef, useState } from "react";
import { getMap } from "@/lib/api";
import type { MapPayload, When } from "@/lib/types";

// Fetches the composed /api/v3/map payload for the active time lens. The hour is
// intentionally not debounced while the dispatch model is being judged: every
// clock/day change should hit the backend and produce a logged lens-specific map.
export function useMapData(when: When, hour: number, date?: string) {
  const [data, setData] = useState<MapPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const prevWhen = useRef<When | null>(null);

  const fetchMap = useCallback(
    (h: number, force: boolean) => {
      let on = true;
      setLoading(true);
      getMap(when, h, when === "custom" ? date : undefined, force)
        .then((d) => on && setData(d))
        .finally(() => on && setLoading(false));
      return () => {
        on = false;
      };
    },
    [when, date],
  );

  // refetch() always hits the API (used by the govt Force-update + manual refresh).
  const refetch = useCallback(() => fetchMap(hour, true), [fetchMap, hour]);

  useEffect(() => {
    // Force a fresh call when the user (re-)selects "Now" — it must reflect the live
    // moment, not a cached snapshot. Other lenses use the cache for instant scrubs.
    const force = when === "now" && prevWhen.current !== "now";
    prevWhen.current = when;
    return fetchMap(hour, force);
  }, [when, hour, date, fetchMap]);

  return { data, loading, refetch };
}
