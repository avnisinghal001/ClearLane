import { useEffect, useState } from "react";
import { getConfig } from "@/lib/api";

export interface MapKeys {
  restKey: string | null; // from GET /api/config (mappls_key) — tried first for map_load
  staticKey: string | null; // VITE_MAPMYINDIA_KEY (or config) — map_load fallback + Mappls v3
  ready: boolean;
}

// Resolves the map keys once: REST key from /api/config (or the demo bundle),
// static key from VITE_MAPMYINDIA_KEY (falling back to the REST key). `ready`
// flips true once config has resolved so the map only inits with final keys.
export function useMapKeys(): MapKeys {
  const envKey = import.meta.env.VITE_MAPMYINDIA_KEY || null;
  const [state, setState] = useState<MapKeys>({ restKey: null, staticKey: envKey, ready: false });
  useEffect(() => {
    let on = true;
    getConfig()
      .then((c) => {
        if (!on) return;
        const rest = c.mappls_key ?? null;
        setState({ restKey: rest, staticKey: envKey || c.static_key || rest, ready: true });
      })
      .catch(() => on && setState((s) => ({ ...s, ready: true })));
    return () => {
      on = false;
    };
  }, [envKey]);
  return state;
}
