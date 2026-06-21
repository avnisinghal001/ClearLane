"""
Stage 07 (Phase 3b) — tomorrow's hour-by-hour TRAFFIC curve per top corridor.

Uses Mappls Predictive ETA (readme-16): for each top-PIC corridor, query the
predicted travel time for each hour of TOMORROW and turn it into a 24-point
congestion-severity curve:

    severity[h] = clip(1 − free_flow / predicted_time[h], 0, 1)
    predicted_time[h] = ETA(speedTypes=predictive, date_time=1,<tomorrow>Thh:00)
    free_flow         = ETA(speedTypes=optimal)        # typical-day best estimate

This is the ONE forecast that is legitimately about traffic — it comes from
Mappls' own predictive engine, not from our ticket data. We validate it later by
re-polling the realised ETA (MAPE).

GRACEFUL: if the route API is unavailable (no key / quota / product not enabled),
we DO NOT fabricate a curve — we emit `status:"api_unavailable"` and the corridors
list so it fills in automatically once the API is live. (Live ETA values cache in
MongoDB only, with a TTL — Phase-2/3 live tier.)
"""
from __future__ import annotations

import math
import os
import sys
from datetime import date, timedelta

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C          # noqa: E402
import utils as U           # noqa: E402
import mappls as M          # noqa: E402


def _offset_point(lat, lon, d_m, bearing_deg=90.0):
    """Corridor B point: d_m metres east of A (same geometry as stage 05)."""
    dlat = d_m * math.cos(math.radians(bearing_deg)) / 111_320.0
    dlon = d_m * math.sin(math.radians(bearing_deg)) / (111_320.0 * math.cos(math.radians(lat)))
    return lat + dlat, lon + dlon


def run() -> dict:
    pic = pd.read_parquet(C.DATA_PROC / "pic.parquet")
    top = pic.sort_values("pic_score", ascending=False).head(C.PIC_TOP_CORRIDORS)
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    online = M.predictive_available()    # per-hour Predictive-ETA product (not the matrix)

    corridors = []
    if online:
        for _, r in top.iterrows():
            if M.route_down():            # route/predictive API disabled -> stop
                break
            la, lo = float(r["lat"]), float(r["lon"])
            blat, blon = _offset_point(la, lo, C.CORRIDOR_LEN_M)
            free = M.eta_seconds(la, lo, blat, blon, speed="optimal")
            curve = []
            for h in C.FORECAST_ETA_HOURS:
                dt = f"1,{tomorrow}T{h:02d}:00"
                t = M.eta_seconds(la, lo, blat, blon, speed="predictive", date_time=dt)
                sev = (float(np.clip(1.0 - free / t, 0, 1)) if (t and free and t > 0) else None)
                curve.append(sev)
            corridors.append({"h3_r10": r["h3_r10"], "lat": la, "lon": lo,
                              "severity_curve": curve})
            M.flush()

    have = any(c for c in corridors if any(s is not None for s in c["severity_curve"]))
    out = {
        "date": tomorrow,
        "status": "ok" if have else "api_unavailable",
        "hours": C.FORECAST_ETA_HOURS,
        "n_corridors": len(top),
        "note": ("Mappls Predictive ETA per hour of tomorrow -> congestion-severity "
                 "curve. Traffic forecast from Mappls, NOT from ticket data."
                 if have else
                 "Route/Predictive-ETA API unavailable (no key / quota / product not "
                 "enabled). Corridors listed; curves fill once the API is live."),
        "corridors": corridors if have else
                     top[["h3_r10", "lat", "lon"]].to_dict(orient="records"),
    }
    U.write_json(C.DATA_PROC / "forecast_eta.json", out)
    print(f"[07_forecast_eta] tomorrow={tomorrow} status={out['status']} "
          f"corridors={out['n_corridors']} (online={online})")
    return out


if __name__ == "__main__":
    run()
