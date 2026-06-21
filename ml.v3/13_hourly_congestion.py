"""
Stage 13 (Phase 9) — Hourly congestion overlay (the honest "24 heatmaps").

Emits a 24-hour TYPICAL-congestion shape per road class so the map can modulate
its *congestion* layer by hour HONESTLY:

    intensity(cell, hour) = historical_propensity(cell)        # day-of-week, real
                          x congestion_at_hour(road_class, h)   # this curve, typical
                          x live_adjustment(cell)               # decaying boost (API)

The curve is MODELED from documented Bengaluru commute peaks (config.HOURLY_*),
NOT measured from tickets — the ticket timestamp is the UPLOAD time, not the
parking time, so ticket COUNTS never legitimately vary by hour. Only congestion
(which genuinely varies by hour) drives the per-hour change. Fully offline +
deterministic; the backend reads this artifact (with a constant fallback) and may
refine a cell's amplitude from Mappls TYPICAL-traffic ETA where available.

Output: data/processed/v3/hourly_congestion.json
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C          # noqa: E402
import utils as U           # noqa: E402


def _curve(amp: float) -> list[float]:
    """Clip(floor + base*amp, 0, 1) — a road-class congestion curve, 24 values."""
    return [round(min(1.0, max(0.0, C.HOURLY_CONGESTION_FLOOR + b * amp)), 4)
            for b in C.HOURLY_CONGESTION_BASE]


def run() -> dict:
    curves = {cls: _curve(amp) for cls, amp in C.HOURLY_CONGESTION_CLASS_AMP.items()}
    global_curve = _curve(C.HOURLY_CONGESTION_GLOBAL_AMP)

    out = {
        "provenance": C.HOURLY_CONGESTION_PROVENANCE,
        "note": ("Modeled TYPICAL congestion by hour (documented Bengaluru commute "
                 "peaks). NOT measured from tickets — ticket time is upload time, "
                 "not parking time; ticket counts never vary by hour. Only the "
                 "congestion layer changes by hour."),
        "hours": list(range(24)),
        "peaks": C.HOURLY_CONGESTION_PEAKS,
        "curves": curves,            # road_class -> [24] in 0..1
        "global": global_curve,      # default when a cell's road class is unknown
    }
    U.write_json(C.DATA_PROC / "hourly_congestion.json", out)

    # console summary (INFO; this stage has no hard self-check target)
    peak_evening = C.HOURLY_CONGESTION_PEAKS["evening"]
    print(f"   hourly congestion: provenance={out['provenance']} · "
          f"classes={len(curves)} · evening peak h{peak_evening} "
          f"(ring={curves['ring_road'][peak_evening]} vs local={curves['local'][peak_evening]})")
    return out


if __name__ == "__main__":
    run()
