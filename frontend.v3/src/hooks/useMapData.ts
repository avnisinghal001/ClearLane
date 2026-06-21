import { useCallback, useEffect, useState } from "react";
import { getMap } from "@/lib/api";
import type { MapPayload, When } from "@/lib/types";

// Fetches the composed /api/v3/map payload for the active time lens, re-querying
// when `when`/`hour` change.
export function useMapData(when: When, hour: number) {
  const [data, setData] = useState<MapPayload | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    const h = hour; // hour drives the heatmap in every mode (live + forecast)
    getMap(when, h)
      .then(setData)
      .finally(() => setLoading(false));
  }, [when, hour]);

  useEffect(() => {
    let on = true;
    setLoading(true);
    const h = hour; // hour drives the heatmap in every mode (live + forecast)
    getMap(when, h)
      .then((d) => on && setData(d))
      .finally(() => on && setLoading(false));
    return () => {
      on = false;
    };
  }, [when, hour]);

  return { data, loading, refetch: load };
}
