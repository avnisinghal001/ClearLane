"""Geographic validation of the Whitefield demo region.

A historical station assignment (`mode_police_station`) is the *dominant station
of the tickets in a cell* — it is NOT an official jurisdiction polygon. This
module attaches a demonstration safety boundary (bbox), honours explicit
exclusions, and optionally enriches with reverse geocoding. Optional reverse-geocode
failure must never silently delete a valid candidate.
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd

STATUS_PASSED = "PASSED"
STATUS_PASSED_WARN = "PASSED_WITH_WARNING"
STATUS_EXCLUDED_BBOX = "EXCLUDED_OUTSIDE_BBOX"
STATUS_EXCLUDED_EXPLICIT = "EXCLUDED_EXPLICITLY"
STATUS_RG_UNAVAILABLE = "REVERSE_GEOCODE_UNAVAILABLE"
STATUS_MANUAL = "MANUAL_REVIEW_REQUIRED"


def _bbox(config: dict[str, Any]) -> dict[str, float]:
    return config["region"]["approximate_demo_bbox"]


def inside_bbox(lat: float, lng: float, bbox: dict[str, float]) -> bool:
    return (
        bbox["minimum_latitude"] <= lat <= bbox["maximum_latitude"]
        and bbox["minimum_longitude"] <= lng <= bbox["maximum_longitude"]
    )


def validate_row(
    h3: str,
    lat: float,
    lng: float,
    config: dict[str, Any],
    explicit_excluded: dict[str, str],
    reverse_geocode: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    bbox = _bbox(config)
    in_box = inside_bbox(lat, lng, bbox)

    result: dict[str, Any] = {
        "h3_res10": h3,
        "inside_demo_bbox": bool(in_box),
        "reverse_geocoded_locality": None,
        "reverse_geocoded_sub_locality": None,
        "formatted_address": None,
        "region_validation_status": STATUS_PASSED,
        "region_exclusion_reason": "",
    }

    if h3 in explicit_excluded:
        result["region_validation_status"] = STATUS_EXCLUDED_EXPLICIT
        result["region_exclusion_reason"] = explicit_excluded[h3]
        return result

    if not in_box:
        result["region_validation_status"] = STATUS_EXCLUDED_BBOX
        result["region_exclusion_reason"] = "OUTSIDE_DEMO_BBOX"
        return result

    if reverse_geocode is None:
        # Optional enrichment unavailable: this is NOT a deletion. Keep candidate.
        result["region_validation_status"] = STATUS_PASSED
        return result

    result["reverse_geocoded_locality"] = reverse_geocode.get("locality")
    result["reverse_geocoded_sub_locality"] = reverse_geocode.get("subLocality")
    result["formatted_address"] = reverse_geocode.get("formatted_address")
    result["region_validation_status"] = STATUS_PASSED
    return result


def validate_candidates(
    candidates: pd.DataFrame,
    config: dict[str, Any],
    reverse_geocodes: Optional[dict[str, dict[str, Any]]] = None,
) -> pd.DataFrame:
    """Attach region-validation columns. `reverse_geocodes` maps h3 -> rev-geocode dict."""
    excluded = {
        str(i["h3_res10"]): str(i.get("reason", "EXPLICITLY_EXCLUDED"))
        for i in config["region"].get("explicitly_excluded_h3", []) or []
    }
    rg = reverse_geocodes or {}
    rows = []
    for _, r in candidates.iterrows():
        rows.append(
            validate_row(
                str(r["h3_res10"]),
                float(r["centroid_latitude"]),
                float(r["centroid_longitude"]),
                config,
                excluded,
                rg.get(str(r["h3_res10"])),
            )
        )
    rv = pd.DataFrame(rows).set_index("h3_res10")
    out = candidates.copy()
    for col in rv.columns:
        out[col] = out["h3_res10"].map(rv[col])
    return out
