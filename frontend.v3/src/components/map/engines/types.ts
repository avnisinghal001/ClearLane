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
  setCircles(circles: CircleSpec[]): void;
  setHeat(points: HeatPoint[], on: boolean): void;
  setPins(pins: PinSpec[]): void;
  setPolylines(lines: PolylineSpec[]): void;
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
