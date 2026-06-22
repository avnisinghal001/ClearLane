from __future__ import annotations

from typing import Any

import pandas as pd


REQUIRED_MAPPING_COLUMNS = [
    "record_id_normalized",
    "latitude_numeric",
    "longitude_numeric",
    "created_date",
    "device_id",
    "created_by_id",
    "vehicle_number_normalized",
    "vehicle_type_normalized",
    "primary_violation_label",
    "contains_parking_related_label",
    "police_station_normalized",
    "junction_name_normalized",
    "validation_status_normalized",
    "is_approved",
    "is_rejected",
    "quality_weight_candidate",
    "record_usable_for_spatial_analysis",
    "record_usable_for_exposure_analysis",
]


def h3_library():
    try:
        import h3  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "The h3 package is required for Phase 2 spatial assignment. "
            "Install requirements-phase2.txt before running Phase 2."
        ) from exc
    return h3


def latlng_to_cell(latitude: float, longitude: float, resolution: int) -> str:
    h3 = h3_library()
    if hasattr(h3, "latlng_to_cell"):
        return h3.latlng_to_cell(float(latitude), float(longitude), int(resolution))
    return h3.geo_to_h3(float(latitude), float(longitude), int(resolution))


def cell_to_parent(cell: str, resolution: int) -> str:
    h3 = h3_library()
    if hasattr(h3, "cell_to_parent"):
        return h3.cell_to_parent(cell, int(resolution))
    return h3.h3_to_parent(cell, int(resolution))


def is_valid_cell(cell: str) -> bool:
    h3 = h3_library()
    if hasattr(h3, "is_valid_cell"):
        return bool(h3.is_valid_cell(cell))
    return bool(h3.h3_is_valid(cell))


def _truthy(series: pd.Series) -> pd.Series:
    if series.dtype == bool:
        return series.fillna(False)
    return series.fillna(False).map(lambda x: str(x).strip().lower() in {"true", "1", "yes"})


def assign_h3_cells(df: pd.DataFrame, resolution: int = 10,
                    parent_resolution: int = 9) -> pd.DataFrame:
    missing = [c for c in ("latitude_numeric", "longitude_numeric") if c not in df.columns]
    if missing:
        raise ValueError("Missing coordinate columns for H3 assignment: " + ", ".join(missing))

    work = df.copy()
    if "record_id_normalized" not in work.columns and "id" in work.columns:
        work["record_id_normalized"] = work["id"].astype("string")
    if "record_usable_for_spatial_analysis" in work.columns:
        work = work[_truthy(work["record_usable_for_spatial_analysis"])].copy()

    work = work.dropna(subset=["latitude_numeric", "longitude_numeric"]).copy()
    work["h3_res10"] = [
        latlng_to_cell(lat, lon, resolution)
        for lat, lon in zip(work["latitude_numeric"], work["longitude_numeric"], strict=False)
    ]
    work["h3_res9"] = [cell_to_parent(cell, parent_resolution) for cell in work["h3_res10"]]

    for col in REQUIRED_MAPPING_COLUMNS:
        if col not in work.columns:
            work[col] = pd.NA

    output_cols = REQUIRED_MAPPING_COLUMNS + ["created_date", "h3_res10", "h3_res9", "phase2_population"]
    output_cols = list(dict.fromkeys([c for c in output_cols if c in work.columns]))
    return work[output_cols].copy()


def h3_assignment_report(source_rows: int, mapping: pd.DataFrame,
                         resolution: int, parent_resolution: int) -> dict[str, Any]:
    validation = validate_h3_mapping(mapping, source_rows, resolution, parent_resolution)
    return {
        "status": validation["status"],
        "source_rows": int(source_rows),
        "mapped_spatial_rows": int(len(mapping)),
        "h3_resolution": int(resolution),
        "h3_parent_resolution": int(parent_resolution),
        "unique_h3_res10": int(mapping["h3_res10"].nunique()) if "h3_res10" in mapping else 0,
        "unique_h3_res9": int(mapping["h3_res9"].nunique()) if "h3_res9" in mapping else 0,
        "coordinate_order": "lat,lng passed to h3.latlng_to_cell",
        "coordinates_rounded_before_h3": False,
        **validation,
    }


def validate_h3_mapping(mapping: pd.DataFrame, production_rows: int,
                        resolution: int = 10, parent_resolution: int = 9) -> dict[str, Any]:
    failures: list[str] = []
    if len(mapping) != int(production_rows):
        failures.append(f"H3 mapped rows {len(mapping)} != production rows {production_rows}.")
    if mapping["h3_res10"].isna().any():
        failures.append("One or more production spatial rows is missing h3_res10.")
    invalid = [cell for cell in mapping["h3_res10"].dropna().astype(str).unique() if not is_valid_cell(cell)]
    if invalid:
        failures.append(f"Invalid H3 cells found: {len(invalid)}.")
    wrong_parent = 0
    for cell, parent in zip(mapping["h3_res10"], mapping["h3_res9"], strict=False):
        if pd.isna(cell) or pd.isna(parent):
            wrong_parent += 1
        elif cell_to_parent(str(cell), parent_resolution) != str(parent):
            wrong_parent += 1
    if wrong_parent:
        failures.append(f"Rows with incorrect h3_res9 parent: {wrong_parent}.")
    return {
        "status": "FAIL" if failures else "PASS",
        "failures": failures,
        "failure_count": len(failures),
        "row_count_reconciled": len(mapping) == int(production_rows),
        "valid_h3_res10_cells": len(invalid) == 0,
        "correct_h3_res9_parent_rows": int(len(mapping) - wrong_parent),
        "incorrect_h3_res9_parent_rows": int(wrong_parent),
    }
