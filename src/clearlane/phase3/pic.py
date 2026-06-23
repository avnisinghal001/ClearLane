"""Parking-Induced Congestion (PIC) score and ranking.

    PIC = normalized_propensity x congestion_severity

No hidden weights. No regional re-normalization of propensity. PIC is only
computed for cells with a valid historical propensity, a valid live observation,
a usable baseline, and finite congestion severity — all from one completed poll
cycle. Otherwise pic_status = NOT_COMPUTED.
"""

from __future__ import annotations

import math
from typing import Any, Optional

import pandas as pd

NOT_COMPUTED = "NOT_COMPUTED"
COMPUTED = "COMPUTED"


def pic_score(normalized_propensity: Optional[float], congestion_severity: Optional[float]) -> Optional[float]:
    if normalized_propensity is None or congestion_severity is None:
        return None
    if not (math.isfinite(normalized_propensity) and math.isfinite(congestion_severity)):
        return None
    if not (0.0 <= normalized_propensity <= 1.0):
        return None
    if not (0.0 <= congestion_severity <= 1.0):
        return None
    val = normalized_propensity * congestion_severity
    return min(1.0, max(0.0, val))


def rank_pic(df: pd.DataFrame, poll_cycle_id: str) -> pd.DataFrame:
    """Rank rows by PIC for a single completed poll cycle.

    Expects columns: h3_res10, normalized_propensity, congestion_severity,
    baseline_usable (bool), live_observation_valid (bool).
    Adds pic_score, pic_status, pic_rank, pic_percentile,
    whitefield_pic_rank, whitefield_pic_percentile.
    """
    out = df.copy()
    out["poll_cycle_id"] = poll_cycle_id

    def _row_pic(r: pd.Series) -> Optional[float]:
        if not bool(r.get("live_observation_valid", False)):
            return None
        if not bool(r.get("baseline_usable", False)):
            return None
        return pic_score(r.get("normalized_propensity"), r.get("congestion_severity"))

    out["pic_score"] = out.apply(_row_pic, axis=1)
    # apply() coerces None -> NaN, so test finiteness rather than identity.
    out["pic_status"] = out["pic_score"].apply(lambda v: COMPUTED if pd.notna(v) else NOT_COMPUTED)

    ranked = out[out["pic_status"] == COMPUTED].copy()
    ranked = ranked.sort_values(
        by=["pic_score", "congestion_severity", "normalized_propensity", "h3_res10"],
        ascending=[False, False, False, True],
        kind="mergesort",
    ).reset_index(drop=True)
    ranked["pic_rank"] = range(1, len(ranked) + 1)
    n = len(ranked)
    if n > 0:
        ranked["pic_percentile"] = ranked["pic_rank"].apply(lambda r: round(1.0 - (r - 1) / n, 6))
    else:
        ranked["pic_percentile"] = []
    # Whitefield-only display rank is identical here (all rows are Whitefield),
    # but provided separately so it stays comparable to a future multi-region run.
    ranked["whitefield_pic_rank"] = ranked["pic_rank"]
    ranked["whitefield_pic_percentile"] = ranked["pic_percentile"]

    rank_map = ranked.set_index("h3_res10")[
        ["pic_rank", "pic_percentile", "whitefield_pic_rank", "whitefield_pic_percentile"]
    ].to_dict("index")

    for col in ["pic_rank", "pic_percentile", "whitefield_pic_rank", "whitefield_pic_percentile"]:
        out[col] = out["h3_res10"].map(lambda h: rank_map.get(h, {}).get(col))
    return out


def validate_bounds(df: pd.DataFrame) -> list[str]:
    """Return a list of violations: PIC out of [0,1], or mixed poll cycles."""
    errs: list[str] = []
    pics = df.loc[df["pic_status"] == COMPUTED, "pic_score"]
    bad = pics[(pics < 0) | (pics > 1) | (~pics.apply(lambda v: math.isfinite(v)))]
    if len(bad) > 0:
        errs.append(f"{len(bad)} PIC values outside [0,1]")
    if "poll_cycle_id" in df.columns:
        cycles = set(df.loc[df["pic_status"] == COMPUTED, "poll_cycle_id"].dropna().unique())
        if len(cycles) > 1:
            errs.append(f"PIC ranking mixes multiple poll cycles: {sorted(cycles)}")
    return errs
