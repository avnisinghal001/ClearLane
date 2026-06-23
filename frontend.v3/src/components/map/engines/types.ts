// One adapter interface, three engines. Role/app code only ever talks to a
// `MapEngine`; it never knows whether MapMyIndia, Mappls v3 or OSM is underneath.
export type EngineId = "mapmyindia" | "mappls" | "osm";

export interface CircleSpec {
  id: string;
  lat: number;
  lon: number;
  radius: number;
  color: string;
  fillColor: string;
  weight: number;
  tooltip?: string;
  onClick?: () => void;
}

export interface PinSpec {
  id: string;
  lat: number;
  lon: number;
  color: string;
  pulse?: boolean;
  popup?: string;
  onClick?: () => void;
  kind?: "pin" | "num" | "user";
  num?: number;
}

export interface PolylineSpec {
  id: string;
  points: [number, number][];
  color: string;
}

// A live-traffic road segment: a SOLID, themed line following the real street
// (Mappls Route ADV geometry), coloured by congestion severity in our P1–P4 ramp.
export interface TrafficLineSpec {
  id: string;
  points: [number, number][];
  color: string;
  tooltip?: string;
}

// Dashed, unfilled overlay ring (e.g. an evening blind-spot marker).
export interface RingSpec {
  id: string;
  lat: number;
  lon: number;
  radius: number;
  color: string;
  weight?: number;
  dashArray?: string;
  tooltip?: string;
}

// A tiny, non-interactive evidence point (a recorded ticket / report location).
export interface DotSpec {
  id: string;
  lat: number;
  lon: number;
  color?: string;
  radius?: number;
}

export interface HeatPoint {
  lat: number;
  lon: number;
  intensity: number;
}

export interface MapEngine {
  id: EngineId;
  label: string;
  priority: number;
  supportsTraffic: boolean;
  setView(center: [number, number], zoom: number, animate?: boolean): void;
  getZoom(): number;
  onMapClick(cb: (lat: number, lon: number) => void): void;
  // long-press (mobile) / right-click (desktop) — used to drop a report pin.
  onLongPress?(cb: (lat: number, lon: number) => void): void;
  setCircles(circles: CircleSpec[]): void;
  setHeat(points: HeatPoint[], on: boolean): void;
  setPins(pins: PinSpec[]): void;
  setPolylines(lines: PolylineSpec[]): void;
  setTrafficLines?(lines: TrafficLineSpec[]): void; // live-traffic road segments (optional)
  setRings(rings: RingSpec[]): void;
  setDots(dots: DotSpec[]): void;
  setTraffic(on: boolean): void;
  invalidate(): void;
  destroy(): void;
}

export interface InitOptions {
  container: HTMLElement;
  center: [number, number];
  zoom: number;
  restKey: string | null;
  staticKey: string | null;
  disableMappls?: boolean; // USE_MAPPLE=false => skip MapMyIndia/Mappls, CARTO basemap only
}

export interface Attempt {
  priority: number;
  label: string;
  ok: boolean;
  error?: string;
}

export interface InitResult {
  engine: MapEngine;
  attempts: Attempt[];
}

// Shared heat ramp (warm, theme-aligned, still legible low→high).
export const HEAT_GRADIENT: Record<number, string> = {
  0.2: "#fde68a",
  0.4: "#fdba74",
  0.6: "#fb923c",
  0.78: "#f97316",
  0.9: "#ea580c",
  1.0: "#b91c1c",
};

export function loadScriptOnce(src: string, marker: string, timeoutMs = 9000): Promise<void> {
  return new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(`script[data-cl="${marker}"]`);
    if (existing) {
      if (existing.dataset.loaded === "1") return resolve();
      existing.addEventListener("load", () => resolve());
      existing.addEventListener("error", () => reject(new Error(`${marker} script error`)));
      return;
    }
    const s = document.createElement("script");
    s.src = src;
    s.async = true;
    s.dataset.cl = marker;
    const to = setTimeout(() => reject(new Error(`${marker} timeout`)), timeoutMs);
    s.onload = () => {
      clearTimeout(to);
      s.dataset.loaded = "1";
      resolve();
    };
    s.onerror = () => {
      clearTimeout(to);
      s.remove();
      reject(new Error(`${marker} script error`));
    };
    document.head.appendChild(s);
  });
}
