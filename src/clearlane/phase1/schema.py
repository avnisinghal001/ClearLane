from __future__ import annotations

import pandas as pd

EXPECTED_COLUMNS = [
    "id", "latitude", "longitude", "location", "vehicle_number", "vehicle_type",
    "description", "violation_type", "offence_code", "created_datetime",
    "closed_datetime", "modified_datetime", "device_id", "created_by_id",
    "center_code", "police_station", "data_sent_to_scita", "junction_name",
    "action_taken_timestamp", "data_sent_to_scita_timestamp",
    "updated_vehicle_number", "updated_vehicle_type", "validation_status",
    "validation_timestamp",
]

CRITICAL_COLUMNS = [
    "id", "latitude", "longitude", "vehicle_number", "vehicle_type",
    "violation_type", "created_datetime", "device_id", "created_by_id",
    "police_station", "junction_name",
]

COLUMN_ROLES = {
    "id": "primary record key",
    "latitude": "coordinate",
    "longitude": "coordinate",
    "vehicle_number": "anonymized entity identifier",
    "device_id": "enforcement exposure identifier",
    "created_by_id": "officer/creator exposure identifier",
    "created_datetime": "date-level temporal source",
    "validation_status": "quality/confidence source",
    "police_station": "administrative ownership",
    "junction_name": "operational location context",
}

LOGICAL_TYPES = {
    "latitude": "numeric coordinate",
    "longitude": "numeric coordinate",
    "created_datetime": "timestamp",
    "modified_datetime": "timestamp",
    "closed_datetime": "timestamp",
    "action_taken_timestamp": "timestamp",
    "data_sent_to_scita_timestamp": "timestamp",
    "validation_timestamp": "timestamp",
    "data_sent_to_scita": "boolean-like",
}


def validate_schema(raw: pd.DataFrame) -> tuple[pd.DataFrame, list[str], list[str]]:
    rows = []
    missing_critical: list[str] = []
    for col in EXPECTED_COLUMNS:
        present = col in raw.columns
        if not present and col in CRITICAL_COLUMNS:
            missing_critical.append(col)
        s = raw[col] if present else pd.Series(dtype=object)
        rows.append({
            "column_name": col,
            "present": present,
            "expected_role": COLUMN_ROLES.get(col, "source attribute"),
            "raw_dtype": str(s.dtype) if present else None,
            "expected_logical_type": LOGICAL_TYPES.get(col, "string/categorical"),
            "null_count": int(s.isna().sum()) if present else None,
            "null_percentage": round(float(s.isna().mean() * 100), 4) if present and len(s) else None,
            "unique_count": int(s.nunique(dropna=True)) if present else None,
            "validation_status": "PASS" if present else ("FAIL" if col in CRITICAL_COLUMNS else "WARN"),
            "notes": "" if present else "missing critical column" if col in CRITICAL_COLUMNS else "missing nullable/expected column",
        })
    extra = [c for c in raw.columns if c not in EXPECTED_COLUMNS and c != "source_row_number"]
    return pd.DataFrame(rows), missing_critical, extra


def data_dictionary(source_columns: list[str], derived_columns: list[str]) -> pd.DataFrame:
    rows = []
    for col in source_columns:
        rows.append({
            "column_name": col,
            "kind": "source",
            "role": COLUMN_ROLES.get(col, "source attribute"),
            "phase1_policy": "preserved raw source value",
        })
    for col in derived_columns:
        rows.append({
            "column_name": col,
            "kind": "derived",
            "role": "phase1 normalized/profiled field",
            "phase1_policy": "derived without overwriting source columns",
        })
    return pd.DataFrame(rows)

