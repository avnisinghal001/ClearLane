import { useEffect, useState } from "react";
import { getConfig } from "@/lib/api";

// Loads the public Mappls map key once (from VITE_MAPPLS_KEY, then /api/config,
// then the demo bundle). null means: render with Carto/OSM tiles only.
export function useMapKey(): string | null {
  const [key, setKey] = useState<string | null>(null);
  useEffect(() => {
    let on = true;
    getConfig()
      .then((c) => on && setKey(c.mappls_key ?? null))
      .catch(() => on && setKey(null));
    return () => {
      on = false;
    };
  }, []);
  return key;
}
