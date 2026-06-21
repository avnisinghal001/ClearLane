import { useCallback, useEffect, useRef, useState } from "react";
import { getMap } from "@/lib/api";
import { useDebounce } from "./useDebounce";
import type { MapPayload, When } from "@/lib/types";

// Fetches the composed /api/v3/map payload for the active time lens. The hour is
// DEBOUNCED (~300ms) so scrubbing the slider doesn't fire a request per tick; the
// settled value triggers the fetch. `when`/`date` changes fetch immediately. The
// "Now" lens (and refetch()) FORCE-hits the API for fresh live state, bypassing the
// client cache — the Google-style "give me the current moment" action.
export function useMapData(when: When, hour: number, date?: string) {
  const [data, setData] = useState<MapPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const debouncedHour = useDebounce(hour, 300);
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
    return fetchMap(debouncedHour, force);
  }, [when, debouncedHour, date, fetchMap]);

  return { data, loading, refetch };
}
