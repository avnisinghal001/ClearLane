"""Reference-duration baselines.

The "non-traffic" provider duration is a *provisional* baseline, never claimed as
true free-flow time. Production baseline hierarchy:

  1. rolling 10th percentile of valid LIVE ETA observations  -> READY_ROLLING_P10
  2. Mappls non-traffic Matrix duration                      -> PROVISIONAL_MAPPLS_NON_TRAFFIC
  3. Route ADV non-traffic duration                          -> PROVISIONAL_MAPPLS_NON_TRAFFIC
  4. rolling minimum (diagnostics only)

A baseline becomes READY only when enough valid LIVE samples across enough
distinct dates and hours exist. Replay observations never update a live baseline.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

READY_ROLLING_P10 = "READY_ROLLING_P10"
PROVISIONAL_MAPPLS = "PROVISIONAL_MAPPLS_NON_TRAFFIC"
PROVISIONAL_INSUFFICIENT = "PROVISIONAL_INSUFFICIENT_HISTORY"
UNAVAILABLE = "UNAVAILABLE"


def percentile(values: list[float], q: float) -> Optional[float]:
    """Linear-interpolation percentile (q in [0,1])."""
    vals = sorted(v for v in values if v is not None and math.isfinite(v))
    if not vals:
        return None
    if len(vals) == 1:
        return vals[0]
    pos = q * (len(vals) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return vals[lo]
    frac = pos - lo
    return vals[lo] + (vals[hi] - vals[lo]) * frac


@dataclass
class BaselineConfig:
    percentile_q: float = 0.10
    minimum_valid_samples: int = 20
    minimum_distinct_dates: int = 2
    minimum_distinct_hours: int = 3


def config_from(config: dict[str, Any]) -> BaselineConfig:
    b = config["baseline"]
    return BaselineConfig(
        percentile_q=float(b.get("percentile", 0.10)),
        minimum_valid_samples=int(b.get("minimum_valid_samples", 20)),
        minimum_distinct_dates=int(b.get("minimum_distinct_dates", 2)),
        minimum_distinct_hours=int(b.get("minimum_distinct_hours", 3)),
    )


def compute_baseline(
    *,
    live_eta_samples: list[tuple[datetime, float]],
    provider_non_traffic_s: Optional[float],
    route_adv_non_traffic_s: Optional[float] = None,
    cfg: Optional[BaselineConfig] = None,
) -> dict[str, Any]:
    """Compute a baseline from valid LIVE ETA samples + provider reference durations.

    `live_eta_samples` are (observed_at, duration_s) tuples — already filtered to
    valid LIVE observations (replay excluded by the caller).
    """
    cfg = cfg or BaselineConfig()
    durations = [d for (_, d) in live_eta_samples if d is not None and math.isfinite(d) and d > 0]
    dates = {ts.date() for (ts, d) in live_eta_samples if d is not None}
    hours = {ts.hour for (ts, d) in live_eta_samples if d is not None}

    rolling_p10 = percentile(durations, cfg.percentile_q) if durations else None
    rolling_min = min(durations) if durations else None

    ready = (
        len(durations) >= cfg.minimum_valid_samples
        and len(dates) >= cfg.minimum_distinct_dates
        and len(hours) >= cfg.minimum_distinct_hours
    )

    provider = provider_non_traffic_s if provider_non_traffic_s is not None else route_adv_non_traffic_s

    if ready and rolling_p10 is not None:
        method = "rolling_p10"
        status = READY_ROLLING_P10
        free_flow = rolling_p10
    elif provider is not None and math.isfinite(provider) and provider > 0:
        method = "provider_non_traffic"
        status = (
            PROVISIONAL_MAPPLS if durations == [] or not ready else PROVISIONAL_MAPPLS
        )
        free_flow = provider
        if not durations:
            status = PROVISIONAL_MAPPLS
        elif not ready:
            status = PROVISIONAL_INSUFFICIENT if rolling_p10 is None else PROVISIONAL_MAPPLS
    else:
        method = "none"
        status = UNAVAILABLE
        free_flow = None

    return {
        "baseline_method": method,
        "baseline_status": status,
        "free_flow_reference_duration_s": free_flow,
        "rolling_p10_duration_s": rolling_p10,
        "rolling_minimum_duration_s": rolling_min,
        "provider_non_traffic_duration_s": provider_non_traffic_s,
        "route_adv_non_traffic_duration_s": route_adv_non_traffic_s,
        "sample_count": len(durations),
        "distinct_date_count": len(dates),
        "distinct_hour_count": len(hours),
    }


def is_usable(status: str) -> bool:
    return status in (READY_ROLLING_P10, PROVISIONAL_MAPPLS, PROVISIONAL_INSUFFICIENT)
