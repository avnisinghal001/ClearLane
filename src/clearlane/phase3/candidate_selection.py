"""Deterministic Whitefield candidate selection.

Selection is derived purely from Phase 2 fields — station, eligibility, spatial
status, explicit exclusions, corrected rank, and a deterministic tie-break. No
hardcoded H3 list participates in the production path; the known expected list is
only a regression check used by tests.

Whitefield normalized_propensity is used as-is (the citywide Phase 2 value) so
Whitefield remains comparable with the rest of Bengaluru. It is never
re-normalized within the region.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def _excluded_h3(config: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in config["region"].get("explicitly_excluded_h3", []) or []:
        out[str(item["h3_res10"])] = str(item.get("reason", "EXPLICITLY_EXCLUDED"))
    return out


def select_candidates(hotspots: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    """Return ordered candidate rows tagged PRIMARY / RESERVE.

    Input must already be canonicalized (see schema.canonicalize).
    """
    region = config["region"]
    sel = config["selection"]
    station_col = region["historical_station_column"]
    station_value = region["historical_station_value"]
    excluded = _excluded_h3(config)

    df = hotspots.copy()
    df = df[df[station_col] == station_value].copy()

    # eligibility
    if sel.get("require_eligible", True):
        df = df[df[sel["eligibility_column"]] == True].copy()  # noqa: E712

    # spatial status: prefer TESTED; fall back only if no preferred remain
    preferred = set(sel.get("preferred_spatial_status", ["TESTED"]))
    fallback = set(sel.get("allow_fallback_spatial_status", []))
    pref_df = df[df["spatial_test_status"].isin(preferred)].copy()
    if len(pref_df) >= (sel["primary_count"] + sel["reserve_count"]):
        df = pref_df
        used_fallback = False
    elif len(pref_df) > 0:
        # keep preferred first, then fallback to backfill
        fb_df = df[df["spatial_test_status"].isin(fallback)].copy()
        df = pd.concat([pref_df, fb_df], ignore_index=True)
        used_fallback = len(fb_df) > 0
    else:
        df = df[df["spatial_test_status"].isin(fallback)].copy()
        used_fallback = True

    # explicit exclusions (e.g. Carmelaram outlier) — never enter primary/reserve
    df["region_exclusion_reason"] = df["h3_res10"].map(excluded).fillna("")
    df = df[~df["h3_res10"].isin(excluded.keys())].copy()

    # deterministic ordering
    tie = sel.get("deterministic_tie_column", "h3_res10")
    # stable preferred-first marker so TESTED outrank fallback at equal rank
    df["_pref"] = (~df["spatial_test_status"].isin(preferred)).astype(int)
    df = df.sort_values(
        by=[sel["rank_column"], "_pref", tie],
        ascending=[True, True, True],
        kind="mergesort",
    ).reset_index(drop=True)

    primary_n = int(sel["primary_count"])
    reserve_n = int(sel["reserve_count"])
    df["candidate_tier"] = "UNSELECTED"
    df.loc[: primary_n - 1, "candidate_tier"] = "PRIMARY"
    df.loc[primary_n : primary_n + reserve_n - 1, "candidate_tier"] = "RESERVE"
    df["selection_rank"] = range(1, len(df) + 1)
    df["selection_reason"] = (
        f"station={station_value};eligible;"
        + df["spatial_test_status"].astype(str)
        + ";rank_asc;tie_h3_asc"
    )
    df["_used_fallback"] = used_fallback

    selected = df[df["candidate_tier"].isin(["PRIMARY", "RESERVE"])].copy()
    selected = selected.drop(columns=["_pref"], errors="ignore")
    return selected


def selection_counts(hotspots: pd.DataFrame, config: dict[str, Any]) -> dict[str, int]:
    region = config["region"]
    sel = config["selection"]
    station_col = region["historical_station_column"]
    station_value = region["historical_station_value"]
    excluded = set(_excluded_h3(config).keys())

    w = hotspots[hotspots[station_col] == station_value]
    eligible = w[w[sel["eligibility_column"]] == True]  # noqa: E712
    tested = eligible[eligible["spatial_test_status"] == "TESTED"]
    tested_after_excl = tested[~tested["h3_res10"].isin(excluded)]
    return {
        "whitefield_h3_cells": int(len(w)),
        "eligible_whitefield_h3_cells": int(len(eligible)),
        "tested_whitefield_h3_cells": int(len(tested)),
        "explicitly_excluded_h3_cells": int(len(set(w["h3_res10"]) & excluded)),
        "eligible_tested_after_exclusions": int(len(tested_after_excl)),
    }
