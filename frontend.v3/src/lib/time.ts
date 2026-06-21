import type { When } from "./types";

// IST = UTC + 5:30. Ticket times track officer shifts, not traffic (honesty).
const IST_OFFSET_MS = 5.5 * 3600 * 1000;

export const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
export const DOW_LONG = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

export function istNow(): Date {
  const d = new Date();
  return new Date(d.getTime() + d.getTimezoneOffset() * 60000 + IST_OFFSET_MS);
}

export function istClock(): string {
  return istNow().toLocaleTimeString("en-GB", { hour12: false }) + " IST";
}

export function istDateLabel(): string {
  return istNow().toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });
}

// Monday-indexed day of week (0=Mon..6=Sun) for the target `when`.
export function dowForWhen(when: When): number {
  const d = istNow();
  if (when === "tomorrow") d.setDate(d.getDate() + 1);
  return (d.getDay() + 6) % 7;
}

export function dowLabel(when: When): string {
  return DOW_LONG[dowForWhen(when)];
}

export function fmtHour(h: number): string {
  const hr = ((h % 24) + 24) % 24;
  const ampm = hr < 12 ? "AM" : "PM";
  const h12 = hr % 12 === 0 ? 12 : hr % 12;
  return `${h12} ${ampm}`;
}

export function relativeTime(iso: string): string {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const diff = Date.now() - t;
  const min = Math.round(diff / 60000);
  if (min < 1) return "just now";
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const d = Math.round(hr / 24);
  if (d < 30) return `${d}d ago`;
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "2-digit" });
}

// The two stated congestion windows are ASSUMPTIONS from domain knowledge,
// not measured peaks — used only to annotate the hour slider.
export function isAssumedPeak(h: number): "morning" | "evening" | null {
  if (h >= 8 && h <= 10) return "morning";
  if (h >= 17 && h <= 20) return "evening";
  return null;
}
