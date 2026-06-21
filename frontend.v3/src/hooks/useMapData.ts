import { useCallback, useEffect, useState } from "react";
import { getMap } from "@/lib/api";
import { useDebounce } from "./useDebounce";
import type { MapPayload, When } from "@/lib/types";

// Fetches the composed /api/v3/map payload for the active time lens. The hour is
// DEBOUNCED (~300ms) so scrubbing the slider doesn't fire a request per tick — the
// variation is real backend data (server-side display_score), so we fetch only the
// settled value. `when`/`date` changes fetch immediately.
export function useMapData(when: When, hour: number, date?: string) {
  const [data, setData] = useState<MapPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const debouncedHour = useDebounce(hour, 300);

  const load = useCallback(() => {
    setLoading(true);
    getMap(when, hour, when === "custom" ? date : undefined)
      .then(setData)
      .finally(() => setLoading(false));
  }, [when, hour, date]);

  useEffect(() => {
    let on = true;
    setLoading(true);
    getMap(when, debouncedHour, when === "custom" ? date : undefined)
      .then((d) => on && setData(d))
      .finally(() => on && setLoading(false));
    return () => {
      on = false;
    };
  }, [when, debouncedHour, date]);

  return { data, loading, refetch: load };
}
