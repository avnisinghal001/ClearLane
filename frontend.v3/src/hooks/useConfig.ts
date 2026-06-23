import { useEffect, useState } from "react";
import { getConfig } from "@/lib/api";

export interface MapKeys {
  restKey: string | null; // from GET /api/config (mappls_key) — tried first for map_load
  staticKey: string | null; // VITE_MAPMYINDIA_KEY (or config) — map_load fallback + Mappls v3
  useMappls: boolean; // backend USE_MAPPLE flag — false => CARTO basemap only (Avni's)
  ready: boolean;
}

// Resolves the map keys once: REST key from /api/config (or the demo bundle),
// static key from VITE_MAPMYINDIA_KEY (falling back to the REST key). `ready`
// flips true once config has resolved so the map only inits with final keys.
// When the backend sends use_mappls:false (USE_MAPPLE=false) we drop the keys so the
// engine chain skips MapMyIndia/Mappls and renders on the CARTO basemap.
export function useMapKeys(): MapKeys {
  const envKey = import.meta.env.VITE_MAPMYINDIA_KEY || null;
  // Hard frontend kill switch: VITE_USE_MAPPLE=false forces the CARTO basemap (Avni's)
  // and never touches MapMyIndia/Mappls — independent of the backend /api/config (so it
  // holds even when the API is unreachable and getConfig falls back to the demo bundle).
  const force = String(import.meta.env.VITE_USE_MAPPLE ?? "").trim().toLowerCase();
  const forceOff = ["false", "0", "no", "off"].includes(force);
  const [state, setState] = useState<MapKeys>({
    restKey: null, staticKey: forceOff ? null : envKey, useMappls: !forceOff, ready: false,
  });
  useEffect(() => {
    let on = true;
    if (forceOff) {
      setState({ restKey: null, staticKey: null, useMappls: false, ready: true });
      return;
    }
    getConfig()
      .then((c) => {
        if (!on) return;
        const use = c.use_mappls !== false;
        const rest = c.mappls_key ?? null;
        setState({
          restKey: use ? rest : null,
          staticKey: use ? envKey || c.static_key || rest : null,
          useMappls: use,
          ready: true,
        });
      })
      .catch(() => on && setState((s) => ({ ...s, ready: true })));
    return () => {
      on = false;
    };
  }, [envKey, forceOff]);
  return state;
}
