import L from "leaflet";

// Teardrop pin as a divIcon (avoids the broken default-marker image issue and
// lets us colour pins by role/state).
export function pinIcon(color: string, pulse = false): L.DivIcon {
  return L.divIcon({
    className: "",
    html: `<div class="cl-pin ${pulse ? "cl-pulse" : ""}" style="
      width:18px;height:18px;border-radius:50% 50% 50% 0;transform:rotate(-45deg);
      background:${color};border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.4)"></div>`,
    iconSize: [18, 18],
    iconAnchor: [9, 18],
    popupAnchor: [0, -16],
  });
}

export function dotIcon(color: string): L.DivIcon {
  return L.divIcon({
    className: "",
    html: `<div style="width:14px;height:14px;border-radius:50%;background:${color};
      border:3px solid #fff;box-shadow:0 0 0 2px ${color}55"></div>`,
    iconSize: [14, 14],
    iconAnchor: [7, 7],
  });
}

export function numIcon(n: number, color: string): L.DivIcon {
  return L.divIcon({
    className: "",
    html: `<div style="min-width:20px;height:20px;padding:0 4px;border-radius:10px;background:${color};
      color:#fff;font:700 11px/20px Inter,sans-serif;text-align:center;border:2px solid #fff;
      box-shadow:0 1px 3px rgba(0,0,0,.4)">${n}</div>`,
    iconSize: [20, 20],
    iconAnchor: [10, 10],
  });
}

export function userIcon(): L.DivIcon {
  return L.divIcon({
    className: "",
    html: `<div style="position:relative">
      <div class="cl-pulse" style="width:16px;height:16px;border-radius:50%;background:#2563eb;border:3px solid #fff;box-shadow:0 0 0 2px #2563eb55"></div>
    </div>`,
    iconSize: [16, 16],
    iconAnchor: [8, 8],
  });
}
