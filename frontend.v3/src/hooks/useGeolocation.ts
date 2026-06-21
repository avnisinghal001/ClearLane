import { useCallback, useEffect, useState } from "react";

export interface GeoState {
  coords: [number, number] | null;
  status: "idle" | "locating" | "ok" | "denied" | "unavailable";
  accuracy: number | null;
}

// Bengaluru bbox guard — ignore a location far outside the city (keeps the demo
// camera sensible when a judge runs it from elsewhere).
const BBOX = { latMin: 12.7, latMax: 13.4, lonMin: 77.3, lonMax: 77.9 };
const inCity = (lat: number, lon: number) =>
  lat >= BBOX.latMin && lat <= BBOX.latMax && lon >= BBOX.lonMin && lon <= BBOX.lonMax;

export function useGeolocation(auto = true) {
  const [state, setState] = useState<GeoState>({ coords: null, status: "idle", accuracy: null });

  const request = useCallback(() => {
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      setState((s) => ({ ...s, status: "unavailable" }));
      return;
    }
    setState((s) => ({ ...s, status: "locating" }));
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const { latitude, longitude, accuracy } = pos.coords;
        setState({
          coords: [latitude, longitude],
          status: inCity(latitude, longitude) ? "ok" : "unavailable",
          accuracy,
        });
      },
      () => setState((s) => ({ ...s, status: "denied" })),
      { enableHighAccuracy: true, timeout: 8000, maximumAge: 60000 },
    );
  }, []);

  useEffect(() => {
    if (auto) request();
  }, [auto, request]);

  // Only surface in-city coordinates to the camera.
  const cityCoords = state.coords && inCity(state.coords[0], state.coords[1]) ? state.coords : null;
  return { ...state, cityCoords, request };
}
