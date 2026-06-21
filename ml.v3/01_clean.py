"""
Stage 01 — load -> IST-convert -> parse violations -> FILTER -> derive weights.

This is the data-cleaning + first feature pass. It reads ALL 24 raw columns
(skipping only the 3 that are 100% empty) so downstream stage 03 can engineer a
feature from every usable field (honesty goal C9).

WORKED EXAMPLE (real row FKID000000):
  raw : lat=12.9255567, lon=77.618665, vehicle_type=CAR,
        violation_type=["WRONG PARKING","PARKING NEAR ROAD CROSSING"],
        validation_status=approved, created_datetime=2023-11-20 00:28:46+00
  ->  created_ist        = 2023-11-20 05:58:46   (UTC +5:30)
      dow_ist            = 0 (Monday),  hour_ist = 5
      row_severity       = max(0.50 WRONG PARKING, 0.90 ROAD CROSSING) = 0.90
      vehicle_wt (CAR)   = 0.60
      confidence         = high (approved)  -> confidence_mult = 1.0
      event_weight       = 0.90 × 0.60 × 1.0 = 0.54

FILTERS (each logged): drop rejected/duplicate validation_status (~28%), drop rows
with no parking-relevant violation, drop rows outside the Bengaluru bbox / missing
coords. Self-check target: ~248,374 rows remain (~16.8% removed).
"""
from __future__ import annotations

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C          # noqa: E402
import utils as U           # noqa: E402

# All 24 columns EXCEPT the 3 verified-empty ones (description, closed_datetime,
# action_taken_timestamp). We read every other column so stage 03 can use them.
USECOLS = [
    "id", "latitude", "longitude", "location", "vehicle_number", "vehicle_type",
    "violation_type", "offence_code", "created_datetime", "modified_datetime",
    "device_id", "created_by_id", "center_code", "police_station",
    "data_sent_to_scita", "junction_name", "data_sent_to_scita_timestamp",
    "updated_vehicle_number", "updated_vehicle_type",
    "validation_status", "validation_timestamp",
]


def run() -> pd.DataFrame:
    log_lines: list[str] = []

    def log(msg: str):
        print(f"[01_clean] {msg}")
        log_lines.append(msg)

    log(f"Loading {C.RAW_CSV.name}")
    df = pd.read_csv(
        C.RAW_CSV, usecols=lambda c: c in USECOLS,
        dtype={"id": "string", "vehicle_number": "string", "vehicle_type": "string",
               "violation_type": "string", "offence_code": "string",
               "location": "string", "police_station": "string",
               "junction_name": "string", "device_id": "string",
               "created_by_id": "string", "validation_status": "string",
               "center_code": "string", "updated_vehicle_number": "string",
               "updated_vehicle_type": "string"},
        na_values=["NULL", ""], low_memory=False,
    )
    n0 = len(df)
    log(f"Raw rows loaded: {n0:,}  (verified ground truth: {C.RAW_ROW_COUNT:,})")

    # --- numeric coords --------------------------------------------------- #
    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")

    # --- timestamps -> IST ------------------------------------------------ #
    # Stored UTC; convert to IST (+5:30). We expose DATE-level fields only for the
    # hotspot/forecast work — the HOUR is an upload artifact, not parking time.
    df["created_ist"] = U.to_ist(df["created_datetime"])
    df["modified_ist"] = U.to_ist(df["modified_datetime"])
    df["validation_ist"] = U.to_ist(df["validation_timestamp"])
    df["hour_ist"] = df["created_ist"].dt.hour          # kept for diagnostics only
    df["dow_ist"] = df["created_ist"].dt.dayofweek      # 0=Mon … 6=Sun
    df["date_ist"] = df["created_ist"].dt.date
    df["month_ist"] = df["created_ist"].dt.strftime("%Y-%m")
    df["is_weekend"] = df["dow_ist"] >= 5

    # processing latency (modified − created), in hours — a data-quality feature.
    df["proc_latency_h"] = (
        (df["modified_ist"] - df["created_ist"]).dt.total_seconds() / 3600.0)

    # data_sent_to_scita -> bool (escalation/quality signal).
    df["scita"] = df["data_sent_to_scita"].astype("string").str.upper().eq("TRUE")
    # vehicle correction signal: was the plate/type later corrected?
    df["was_corrected"] = df["updated_vehicle_number"].notna()

    # --- parse violation + offence arrays --------------------------------- #
    df["violation_list"] = df["violation_type"].map(U.parse_array)
    df["n_violations"] = df["violation_list"].map(len)
    df["has_parking_violation"] = df["violation_list"].map(U.has_parking)
    df["primary_violation"] = df["violation_list"].map(U.primary_violation)
    df["row_severity"] = df["violation_list"].map(U.row_severity)
    # prefer the corrected vehicle type when present, else the original.
    veh = df["updated_vehicle_type"].fillna(df["vehicle_type"])
    df["vehicle_type"] = veh
    df["vehicle_wt"] = veh.map(U.vehicle_weight)
    # offence_code -> max auxiliary severity (display/feature only).
    df["offence_severity_aux"] = df["offence_code"].map(
        lambda s: max((C.OFFENCE_CODE_SEVERITY.get(str(x).strip(), 0.0)
                       for x in U.parse_array(s)), default=0.0))

    # --- filters ---------------------------------------------------------- #
    log(f"--- filtering (start {len(df):,}) ---")
    status_norm = df["validation_status"].astype("string").str.lower()

    drop_status = status_norm.isin(C.DROP_VALIDATION_STATUS)
    log(f"drop rejected+duplicate validation_status: -{int(drop_status.sum()):,}")
    df = df[~drop_status].copy()

    no_parking = ~df["has_parking_violation"]
    log(f"drop rows with no parking-relevant violation: -{int(no_parking.sum()):,}")
    df = df[~no_parking].copy()

    out_bbox = ~U.in_bbox(df["latitude"], df["longitude"]) | df["latitude"].isna()
    log(f"drop rows outside Bengaluru bbox / missing coords: -{int(out_bbox.sum()):,}")
    df = df[~out_bbox].copy()

    n1 = len(df)
    log(f"clean rows remaining: {n1:,}  ({100.0*(n0-n1)/n0:.1f}% removed; "
        f"target {C.SELF_CHECK_TARGETS['clean_rows']:,})")

    # --- confidence (Pillar-A multiplier) --------------------------------- #
    status_kept = status_norm.reindex(df.index)
    is_high = status_kept.isin(C.HIGH_CONFIDENCE_STATUS) | df["scita"]
    # is_approved is later aggregated per-cell into an approval_rate quality feature.
    df["is_approved"] = status_kept.isin(C.HIGH_CONFIDENCE_STATUS).fillna(False)
    df["confidence"] = is_high.map({True: "high", False: "medium"})
    df["confidence_mult"] = df["confidence"].map(C.CONFIDENCE_MULT)
    log(f"confidence: high={int((df['confidence']=='high').sum()):,} "
        f"medium={int((df['confidence']=='medium').sum()):,}")

    # event weight (Pillar A): severity × footprint × confidence.
    df["event_weight"] = df["row_severity"] * df["vehicle_wt"] * df["confidence_mult"]

    # --- persist ---------------------------------------------------------- #
    keep = [
        "id", "latitude", "longitude", "location", "vehicle_number", "vehicle_type",
        "vehicle_wt", "primary_violation", "row_severity", "n_violations",
        "offence_severity_aux", "police_station", "junction_name", "center_code",
        "device_id", "created_by_id", "scita", "was_corrected", "is_approved",
        "confidence", "confidence_mult", "event_weight", "proc_latency_h",
        "created_ist", "hour_ist", "dow_ist", "date_ist", "month_ist", "is_weekend",
    ]
    out = df[keep].copy()
    out["violation_list_str"] = df["violation_list"].map(lambda x: "|".join(x))

    C.DATA_PROC.mkdir(parents=True, exist_ok=True)
    out.to_parquet(C.DATA_PROC / "events_clean.parquet", index=False)

    monthly = out["month_ist"].value_counts().sort_index()
    log("monthly (clean): " + ", ".join(f"{k}={v:,}" for k, v in monthly.items()))

    summary = ["ClearLane v3 — cleaning summary (stage 01)", "=" * 48,
               f"data window (verified): {C.TIME_WINDOW_START} -> {C.TIME_WINDOW_END}",
               ""] + log_lines
    (C.REPORTS / "cleaning_summary.txt").write_text("\n".join(summary) + "\n",
                                                    encoding="utf-8")
    print(f"[01_clean] wrote events_clean ({n1:,} rows) + cleaning_summary.txt")
    return out


if __name__ == "__main__":
    run()
