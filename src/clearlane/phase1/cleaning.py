from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .category_normalization import (
    is_null_like,
    normalize_bool,
    normalize_identifier,
    normalize_text,
    normalize_validation_status,
)
from .datetime_utils import parse_datetime_series
from .reporting import dataframe_fingerprint, mask_value, write_json
from .schema import data_dictionary
from .violation_parser import (
    classify_parking,
    parse_offence_codes,
    parse_violation_labels,
    primary_violation,
)

DATETIME_COLUMNS = [
    "created_datetime", "closed_datetime", "modified_datetime",
    "action_taken_timestamp", "data_sent_to_scita_timestamp",
    "validation_timestamp",
]

NORMALIZED_TEXT_COLUMNS = [
    "location", "vehicle_type", "police_station", "junction_name",
]


@dataclass
class Phase1CleanResult:
    accepted: pd.DataFrame
    quarantined: pd.DataFrame
    exact_duplicates: pd.DataFrame
    reports: dict[str, Any]
    output_columns: list[str]


def _null_tokens(config: dict) -> set[str]:
    return set(config.get("cleaning", {}).get("null_tokens", []))


def _safe_source(df: pd.DataFrame) -> pd.DataFrame:
    source_cols = [c for c in df.columns if c != "source_row_number"]
    return df[source_cols].copy()


def _add_reason(reasons: dict[int, list[tuple[str, str]]], idx: int,
                code: str, detail: str) -> None:
    reasons.setdefault(idx, []).append((code, detail))


def _reason_frame(df: pd.DataFrame, reasons: dict[int, list[tuple[str, str]]]) -> pd.DataFrame:
    if not reasons:
        return pd.DataFrame(columns=list(df.columns) + ["record_id", "reason_code", "reason_detail"])
    rows = []
    for idx, vals in sorted(reasons.items(), key=lambda kv: int(df.loc[kv[0], "source_row_number"])):
        row = df.loc[idx].to_dict()
        row["record_id"] = row.get("record_id_normalized") or row.get("id")
        row["reason_code"] = "|".join(code for code, _ in vals)
        row["reason_detail"] = "|".join(detail for _, detail in vals)
        rows.append(row)
    return pd.DataFrame(rows)


def _write_quarantine_files(qdir: Path, quarantined: pd.DataFrame,
                            exact_duplicates: pd.DataFrame) -> None:
    qdir.mkdir(parents=True, exist_ok=True)
    groups = {
        "invalid_coordinates.csv": "INVALID_COORDINATE",
        "invalid_datetimes.csv": "INVALID_CREATED_DATETIME",
        "conflicting_duplicate_ids.csv": "CONFLICTING_DUPLICATE_ID",
        "missing_critical_fields.csv": "MISSING_",
    }
    for name, marker in groups.items():
        if quarantined.empty:
            out = quarantined.copy()
        elif marker == "MISSING_":
            out = quarantined[quarantined["reason_code"].astype(str).str.contains("MISSING_", na=False)]
        else:
            out = quarantined[quarantined["reason_code"].astype(str).str.contains(marker, na=False)]
        out.to_csv(qdir / name, index=False)
    quarantined.to_csv(qdir / "all_quarantined_rows.csv", index=False)
    exact_duplicates.to_csv(qdir / "exact_duplicate_rows.csv", index=False)


def _timestamp_consistency(work: pd.DataFrame, parsed: dict[str, pd.Series]) -> pd.DataFrame:
    rows = []
    created = parsed.get("created_datetime")
    if created is None:
        return pd.DataFrame(rows)
    checks = [
        ("modified_before_created", "modified_datetime"),
        ("validation_before_created", "validation_timestamp"),
        ("scita_before_created", "data_sent_to_scita_timestamp"),
    ]
    for relation, col in checks:
        other = parsed.get(col)
        if other is None:
            continue
        bad_idx = []
        for idx in work.index:
            left = other.loc[idx]
            right = created.loc[idx]
            if pd.notna(left) and pd.notna(right) and left < right:
                bad_idx.append(idx)
        for idx in bad_idx:
            rows.append({
                "source_row_number": int(work.loc[idx, "source_row_number"]),
                "id": work.loc[idx].get("id"),
                "relation": relation,
                "created_datetime_parsed": work.loc[idx].get("created_datetime_parsed"),
                f"{col}_parsed": work.loc[idx].get(f"{col}_parsed"),
            })
    return pd.DataFrame(rows)


def _capability_limitations(accepted: pd.DataFrame) -> pd.DataFrame:
    columns = {c.lower() for c in accepted.columns}
    has_speed = any(c in columns for c in {"speed", "traffic_speed", "travel_speed"})
    has_duration = any(c in columns for c in {"duration", "travel_time", "traffic_duration"})
    has_volume = any(c in columns for c in {"volume", "traffic_volume", "road_occupancy"})
    has_officer_ll = {"officer_latitude", "officer_longitude"}.issubset(columns)
    has_dispatch = any(c in columns for c in {"dispatch_assignment", "dispatch_id", "route_id"})
    action_non_null = bool("action_taken_timestamp" in accepted and accepted["action_taken_timestamp"].map(lambda v: not is_null_like(v)).any())
    rows = [
        {
            "capability": "Live traffic modelling",
            "required_data": "speed/travel-time observations",
            "available": bool(has_speed or has_duration or has_volume),
            "phase1_conclusion": "available" if (has_speed or has_duration or has_volume) else "external source required",
        },
        {
            "capability": "Historical dispatch RL",
            "required_data": "officer trajectories and outcomes",
            "available": bool(has_officer_ll and has_dispatch),
            "phase1_conclusion": "possible" if (has_officer_ll and has_dispatch) else "impossible",
        },
        {
            "capability": "Hourly violation forecast",
            "required_data": "reliable incident time",
            "available": False,
            "phase1_conclusion": "prohibited unless later evidence proves timestamp hour is incident time",
        },
        {
            "capability": "Repeat-offender analysis",
            "required_data": "anonymized vehicle ID",
            "available": bool("vehicle_number_normalized" in accepted and accepted["vehicle_number_normalized"].notna().any()),
            "phase1_conclusion": "available",
        },
        {
            "capability": "Enforcement-bias correction",
            "required_data": "device/date activity",
            "available": bool({"device_id", "created_date"}.issubset(accepted.columns)),
            "phase1_conclusion": "available" if {"device_id", "created_date"}.issubset(accepted.columns) else "unavailable",
        },
        {
            "capability": "Action-response timing",
            "required_data": "resolved time / action taken time",
            "available": action_non_null,
            "phase1_conclusion": "available" if action_non_null else "unavailable",
        },
    ]
    return pd.DataFrame(rows)


def _repeat_summary(accepted: pd.DataFrame) -> dict:
    vehicles = accepted["vehicle_number_normalized"].dropna()
    counts = vehicles.value_counts()
    repeat = counts[counts >= 2]
    repeat_records = int(vehicles.isin(repeat.index).sum())
    return {
        "unique_vehicles": int(counts.size),
        "repeat_vehicles": int(repeat.size),
        "records_belonging_to_repeat_vehicles": repeat_records,
        "percentage_of_records_from_repeat_vehicles": round(100 * repeat_records / len(accepted), 4) if len(accepted) else 0.0,
        "maximum_records_for_one_vehicle": int(counts.max()) if len(counts) else 0,
        "median_records_per_repeat_vehicle": round(float(repeat.median()), 4) if len(repeat) else 0.0,
        "p95_records_per_vehicle": round(float(counts.quantile(0.95)), 4) if len(counts) else 0.0,
    }


def _validation_summary(accepted: pd.DataFrame) -> dict:
    s = accepted["validation_status_normalized"]
    counts = s.value_counts(dropna=False).to_dict()
    recognized = int(s.isin(["APPROVED", "REJECTED", "PENDING"]).sum())
    rejected = int((s == "REJECTED").sum())
    return {
        "approved_count": int((s == "APPROVED").sum()),
        "rejected_count": rejected,
        "pending_count": int((s == "PENDING").sum()),
        "unknown_count": int((s == "UNKNOWN").sum()),
        "unmapped_count": int((s == "UNMAPPED").sum()),
        "counts": {str(k): int(v) for k, v in counts.items()},
        "rejected_percentage_among_recognized_validated_records": round(100 * rejected / recognized, 4) if recognized else None,
    }


def _temporal_artifact_report(accepted: pd.DataFrame) -> dict:
    hours = accepted["created_hour_diagnostic"].dropna().astype(int)
    counts = hours.value_counts().reindex(range(24), fill_value=0).sort_index()
    pct = (counts / max(int(counts.sum()), 1) * 100).round(4)
    month_hour = pd.crosstab(accepted["created_month"], accepted["created_hour_diagnostic"]).reindex(columns=range(24), fill_value=0)
    normalized = month_hour.div(month_hour.sum(axis=1).replace(0, np.nan), axis=0).fillna(0)
    corr = normalized.T.corr() if len(normalized) >= 2 else pd.DataFrame()
    corr_vals = corr.where(~np.eye(len(corr), dtype=bool)).stack() if not corr.empty else pd.Series(dtype=float)
    mean_corr = float(corr_vals.mean()) if len(corr_vals) else None
    pct_15_midnight = round(float(pct.loc[15:23].sum()), 4)
    if mean_corr is not None and mean_corr >= 0.85 and pct_15_midnight >= 50:
        conclusion = "HOUR_AXIS_UNRELIABLE"
    elif (mean_corr is not None and mean_corr >= 0.75) or pct_15_midnight >= 40:
        conclusion = "HOUR_AXIS_SUSPICIOUS"
    else:
        conclusion = "HOUR_AXIS_NOT_YET_PROVEN_UNRELIABLE"
    return {
        "ticket_count_by_hour": {str(int(k)): int(v) for k, v in counts.items()},
        "ticket_percentage_by_hour": {str(int(k)): float(v) for k, v in pct.items()},
        "ticket_count_by_month_and_hour": {
            str(idx): {str(int(k)): int(v) for k, v in row.items()}
            for idx, row in month_hour.iterrows()
        },
        "monthly_hour_distribution_correlation_mean": round(mean_corr, 4) if mean_corr is not None else None,
        "percentage_between_15_00_and_23_59": pct_15_midnight,
        "conclusion": conclusion,
        "note": "Diagnostic only. Phase 1 does not treat hour as parking/incident time.",
    }


def _claims_comparison(accepted: pd.DataFrame, raw_rows: int, quarantined_rows: int,
                       duplicate_rows: int, config: dict, repeat: dict,
                       validation: dict, temporal: dict, parking_summary: dict) -> pd.DataFrame:
    refs = config.get("document_reference_claims", {})
    created_dates = pd.to_datetime(accepted["created_date"], errors="coerce")
    values = {
        "raw_row_count": raw_rows,
        "date_minimum": created_dates.min().date().isoformat() if created_dates.notna().any() else None,
        "date_maximum": created_dates.max().date().isoformat() if created_dates.notna().any() else None,
        "parking_related_percentage": parking_summary["parking_related_percentage"],
        "unique_devices": int(accepted["device_id"].dropna().nunique()) if "device_id" in accepted else None,
        "unique_created_by_ids": int(accepted["created_by_id"].dropna().nunique()) if "created_by_id" in accepted else None,
        "repeat_offender_record_percentage": repeat["percentage_of_records_from_repeat_vehicles"],
        "maximum_records_for_one_vehicle": repeat["maximum_records_for_one_vehicle"],
        "validation_rejection_percentage": validation["rejected_percentage_among_recognized_validated_records"],
        "percentage_from_15_00_to_midnight": temporal["percentage_between_15_00_and_23_59"],
        "police_station_count": int(accepted["police_station_normalized"].dropna().nunique()),
        "junction_count": int(accepted["junction_name_normalized"].dropna().nunique()),
    }
    rows = []
    for claim, value in values.items():
        ref = refs.get(claim)
        status = "NOT_COMPUTABLE_IN_PHASE1" if value is None else "DIFFERENT"
        abs_diff = None
        rel_diff = None
        explanation = ""
        if ref is None:
            explanation = "No document reference value configured for this claim."
        elif value is None:
            explanation = "Current Phase 1 input cannot compute this claim."
        else:
            try:
                fv = float(value)
                fr = float(ref)
                abs_diff = round(fv - fr, 6)
                rel_diff = round(abs_diff / fr * 100, 6) if fr else None
                if abs(abs_diff) < 1e-9:
                    status = "MATCH"
                elif rel_diff is not None and abs(rel_diff) <= 2.0:
                    status = "CLOSE"
                else:
                    status = "DIFFERENT"
                explanation = "Numeric comparison against configured document reference."
            except Exception:
                status = "MATCH" if str(value) == str(ref) else "DIFFERENT"
                explanation = "String/date comparison against configured document reference."
        rows.append({
            "claim_name": claim,
            "document_reference_value": ref,
            "recomputed_value": value,
            "absolute_difference": abs_diff,
            "relative_difference": rel_diff,
            "status": status,
            "explanation": explanation,
        })
    return pd.DataFrame(rows)


def _plots(accepted: pd.DataFrame, raw_null_report: pd.DataFrame, plots_dir: Path) -> list[str]:
    plots_dir.mkdir(parents=True, exist_ok=True)
    made: list[str] = []
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        def save(name: str) -> None:
            plt.tight_layout()
            plt.savefig(plots_dir / name, dpi=140)
            plt.close()
            made.append(name)

        raw_null_report.sort_values("null_percentage", ascending=False).plot.bar(
            x="column", y="null_percentage", legend=False, figsize=(12, 5), title="Null percentages")
        save("null_percentages.png")

        pd.to_datetime(accepted["created_date"], errors="coerce").value_counts().sort_index().plot(
            figsize=(12, 4), title="Records by date")
        save("records_by_date.png")

        accepted["created_day_of_week"].value_counts().reindex(range(7), fill_value=0).plot.bar(
            title="Records by day of week")
        save("records_by_day_of_week.png")

        accepted["created_hour_diagnostic"].value_counts().reindex(range(24), fill_value=0).plot.bar(
            title="Records by diagnostic created hour")
        save("records_by_hour_diagnostic.png")

        month_hour = pd.crosstab(accepted["created_month"], accepted["created_hour_diagnostic"]).reindex(columns=range(24), fill_value=0)
        plt.figure(figsize=(12, 5))
        plt.imshow(month_hour.to_numpy(), aspect="auto")
        plt.yticks(range(len(month_hour.index)), month_hour.index)
        plt.xticks(range(24), range(24))
        plt.title("Month-hour distributions")
        plt.colorbar()
        save("month_hour_distributions.png")

        accepted["vehicle_number_normalized"].dropna().value_counts().clip(upper=20).plot.hist(
            bins=20, title="Repeat-offender distribution")
        save("repeat_offender_distribution.png")

        accepted["validation_status_normalized"].value_counts().plot.bar(
            title="Validation status distribution")
        save("validation_status_distribution.png")
    except Exception:
        pass
    return made


def clean_dataframe(raw: pd.DataFrame, config: dict, reports_dir: str | Path,
                    quarantine_dir: str | Path) -> Phase1CleanResult:
    reports_dir = Path(reports_dir)
    quarantine_dir = Path(quarantine_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)

    source_cols = [c for c in raw.columns if c != "source_row_number"]
    null_tokens = _null_tokens(config)
    parking_labels = {normalize_text(v, uppercase=True) for v in config["violation_labels"]["parking_related"]}
    parking_labels = {v for v in parking_labels if v}

    exact_mask = _safe_source(raw).duplicated(keep="first")
    exact_duplicates = raw[exact_mask].copy()
    work = raw[~exact_mask].copy()

    # Preserve raw columns; every field below is derived.
    work["record_id_normalized"] = work["id"].map(lambda v: normalize_identifier(v, null_tokens))
    for col in ("vehicle_number", "device_id", "created_by_id", "center_code"):
        if col in work:
            work[f"{col}_normalized"] = work[col].map(lambda v: normalize_identifier(v, null_tokens))

    lat_col = config["coordinates"]["latitude_column"]
    lon_col = config["coordinates"]["longitude_column"]
    work["latitude_numeric"] = pd.to_numeric(work[lat_col].map(lambda v: normalize_text(v, null_tokens=null_tokens)), errors="coerce")
    work["longitude_numeric"] = pd.to_numeric(work[lon_col].map(lambda v: normalize_text(v, null_tokens=null_tokens)), errors="coerce")
    work["coordinate_parse_valid"] = work["latitude_numeric"].notna() & work["longitude_numeric"].notna()
    c = config["coordinates"]
    work["coordinate_global_valid"] = (
        work["coordinate_parse_valid"]
        & work["latitude_numeric"].between(c["global_latitude_min"], c["global_latitude_max"])
        & work["longitude_numeric"].between(c["global_longitude_min"], c["global_longitude_max"])
    )
    work["coordinate_zero_zero"] = work["coordinate_parse_valid"] & work["latitude_numeric"].eq(0) & work["longitude_numeric"].eq(0)
    box = c["bengaluru_sanity_box"]
    work["coordinate_bengaluru_sanity_valid"] = (
        work["coordinate_parse_valid"]
        & work["latitude_numeric"].between(box["latitude_min"], box["latitude_max"])
        & work["longitude_numeric"].between(box["longitude_min"], box["longitude_max"])
    )
    work["possible_coordinate_swap"] = (
        work["coordinate_parse_valid"]
        & work["latitude_numeric"].between(box["longitude_min"], box["longitude_max"])
        & work["longitude_numeric"].between(box["latitude_min"], box["latitude_max"])
    )

    parsed_dt: dict[str, pd.Series] = {}
    datetime_report = {}
    for col in DATETIME_COLUMNS:
        if col not in work:
            continue
        iso, valid, rep, parsed_values = parse_datetime_series(
            work[col],
            source_timezone=config["datetime"]["source_timezone"],
            canonical_timezone=config["datetime"]["canonical_timezone"],
            dayfirst=bool(config["datetime"].get("dayfirst", False)),
        )
        work[f"{col}_parsed"] = iso
        work[f"{col}_parse_valid"] = valid
        parsed_dt[col] = parsed_values
        datetime_report[col] = rep

    created = parsed_dt["created_datetime"]
    work["created_date"] = created.map(lambda v: v.date().isoformat() if pd.notna(v) else None)
    work["created_year"] = created.map(lambda v: int(v.year) if pd.notna(v) else None)
    work["created_month"] = created.map(lambda v: f"{v.year:04d}-{v.month:02d}" if pd.notna(v) else None)
    work["created_day_of_week"] = created.map(lambda v: int(v.dayofweek) if pd.notna(v) else None)
    work["created_is_weekend"] = created.map(lambda v: bool(v.dayofweek >= 5) if pd.notna(v) else None)
    work["created_hour_diagnostic"] = created.map(lambda v: int(v.hour) if pd.notna(v) else None)
    write_json(reports_dir / "datetime_report.json", {
        "columns": datetime_report,
        "policy": {
            "canonical_operational_timestamp": "created_datetime_parsed",
            "hour_field": "created_hour_diagnostic",
            "hour_field_is_diagnostic_only": True,
            "source_timezone_for_naive": config["datetime"]["source_timezone"],
            "canonical_timezone": config["datetime"]["canonical_timezone"],
        },
    })

    consistency = _timestamp_consistency(work, parsed_dt)
    consistency.to_csv(reports_dir / "timestamp_consistency_report.csv", index=False)

    unknown_bool = []
    if "data_sent_to_scita" in work:
        work["data_sent_to_scita_boolean"] = work["data_sent_to_scita"].map(lambda v: normalize_bool(v, null_tokens))
        raw_known = ~work["data_sent_to_scita"].map(lambda v: is_null_like(v, null_tokens))
        unknown_bool = work[raw_known & work["data_sent_to_scita_boolean"].isna()]["data_sent_to_scita"].drop_duplicates().tolist()

    for col in NORMALIZED_TEXT_COLUMNS:
        if col in work:
            work[f"{col}_normalized"] = work[col].map(lambda v: normalize_text(v, uppercase=True, null_tokens=null_tokens))
    work["validation_status_normalized"] = work["validation_status"].map(
        lambda v: normalize_validation_status(v, config["validation_status"], null_tokens)
    )
    work["is_validation_known"] = work["validation_status_normalized"].isin(["APPROVED", "REJECTED", "PENDING"])
    work["is_approved"] = work["validation_status_normalized"].eq("APPROVED")
    work["is_rejected"] = work["validation_status_normalized"].eq("REJECTED")
    work["quality_weight_candidate"] = work["validation_status_normalized"].map({
        "APPROVED": 1.0,
        "REJECTED": 0.0,
    })

    labels = work["violation_type"].map(parse_violation_labels)
    work["violation_labels"] = labels.map(lambda xs: json.dumps(xs, ensure_ascii=True))
    work["violation_label_count"] = labels.map(len)
    work["contains_parking_related_label"] = labels.map(lambda xs: classify_parking(xs, parking_labels))
    work["primary_violation_label"] = labels.map(lambda xs: primary_violation(xs, parking_labels))

    offence = work["offence_code"].map(parse_offence_codes)
    work["offence_codes_parsed"] = offence.map(lambda pair: json.dumps(pair[0], ensure_ascii=True))
    work["offence_code_count"] = offence.map(lambda pair: len(pair[0]))
    work["offence_code_parse_valid"] = offence.map(lambda pair: bool(pair[1]))

    work["has_vehicle_number_correction"] = (
        work["updated_vehicle_number"].map(lambda v: not is_null_like(v, null_tokens))
        & (work["updated_vehicle_number"].map(lambda v: normalize_identifier(v, null_tokens))
           != work["vehicle_number"].map(lambda v: normalize_identifier(v, null_tokens)))
    )
    work["has_vehicle_type_correction"] = (
        work["updated_vehicle_type"].map(lambda v: not is_null_like(v, null_tokens))
        & (work["updated_vehicle_type"].map(lambda v: normalize_text(v, uppercase=True, null_tokens=null_tokens))
           != work["vehicle_type"].map(lambda v: normalize_text(v, uppercase=True, null_tokens=null_tokens)))
    )
    work["effective_vehicle_number_candidate"] = np.where(
        work["updated_vehicle_number"].map(lambda v: not is_null_like(v, null_tokens)),
        work["updated_vehicle_number"],
        work["vehicle_number"],
    )
    work["effective_vehicle_type_candidate"] = np.where(
        work["updated_vehicle_type"].map(lambda v: not is_null_like(v, null_tokens)),
        work["updated_vehicle_type"],
        work["vehicle_type"],
    )

    work["record_usable_for_spatial_analysis"] = work["coordinate_global_valid"] & work["created_datetime_parse_valid"]
    work["record_usable_for_exposure_analysis"] = (
        work["record_usable_for_spatial_analysis"]
        & work["device_id"].map(lambda v: not is_null_like(v, null_tokens))
    )
    work["record_usable_for_repeat_offender_analysis"] = work["vehicle_number_normalized"].notna()
    work["record_usable_for_quality_analysis"] = work["is_validation_known"]

    reasons: dict[int, list[tuple[str, str]]] = {}
    for idx, row in work.iterrows():
        if is_null_like(row.get("id"), null_tokens):
            _add_reason(reasons, idx, "MISSING_ID", "id is required for record identity")
        if is_null_like(row.get("device_id"), null_tokens):
            _add_reason(reasons, idx, "MISSING_DEVICE_ID", "device_id is required for exposure analysis")
        if not bool(row.get("coordinate_global_valid")):
            _add_reason(reasons, idx, "INVALID_COORDINATE", "coordinate missing, non-numeric, or globally impossible")
        if not bool(row.get("created_datetime_parse_valid")):
            _add_reason(reasons, idx, "INVALID_CREATED_DATETIME", "created_datetime is missing or unparseable")

    dup_id = work["record_id_normalized"]
    conflicting_ids = set(dup_id[dup_id.notna() & dup_id.duplicated(keep=False)])
    for idx, rid in dup_id.items():
        if rid in conflicting_ids:
            _add_reason(reasons, idx, "CONFLICTING_DUPLICATE_ID", f"id {rid} appears with conflicting source rows")

    quarantined = _reason_frame(work, reasons)
    quarantine_idx = set(reasons)
    accepted = work.drop(index=list(quarantine_idx)).copy()

    _write_quarantine_files(quarantine_dir, quarantined, exact_duplicates)

    outside = work[~work["coordinate_bengaluru_sanity_valid"] & work["coordinate_parse_valid"]].copy()
    outside.to_csv(reports_dir / "outside_bengaluru_sanity_box.csv", index=False)
    swaps = work[work["possible_coordinate_swap"]].copy()
    swaps.to_csv(reports_dir / "possible_coordinate_swaps.csv", index=False)
    write_json(reports_dir / "coordinate_report.json", {
        "input_rows_after_exact_dedup": int(len(work)),
        "coordinate_parse_valid_rows": int(work["coordinate_parse_valid"].sum()),
        "coordinate_global_valid_rows": int(work["coordinate_global_valid"].sum()),
        "coordinate_zero_zero_rows": int(work["coordinate_zero_zero"].sum()),
        "outside_bengaluru_sanity_box_rows": int(len(outside)),
        "possible_coordinate_swap_rows": int(work["possible_coordinate_swap"].sum()),
        "invalid_coordinate_rows": int((~work["coordinate_global_valid"]).sum()),
        "bengaluru_box_is_quarantine_rule": False,
    })

    raw_label_rows = []
    for xs in labels:
        raw_label_rows.extend(xs)
    label_counts = pd.Series(raw_label_rows, dtype="string").value_counts()
    label_dict = pd.DataFrame({
        "label": label_counts.index,
        "count": label_counts.values,
        "parking_related": [label in parking_labels for label in label_counts.index],
        "mapping_version": "configs/phase1.yaml:violation_labels.parking_related",
    })
    label_dict.to_csv(reports_dir / "violation_label_dictionary.csv", index=False)
    unmapped_labels = label_dict[~label_dict["parking_related"]].copy()
    unmapped_labels.to_csv(reports_dir / "unmapped_violation_labels.csv", index=False)

    unparsed_offence = work[~work["offence_code_parse_valid"]][["source_row_number", "id", "offence_code"]].copy()
    unparsed_offence.to_csv(reports_dir / "unparsed_offence_codes.csv", index=False)

    duplicate_report = {
        "exact_duplicate_rows_removed": int(len(exact_duplicates)),
        "conflicting_duplicate_id_rows": int(quarantined["reason_code"].astype(str).str.contains("CONFLICTING_DUPLICATE_ID", na=False).sum()) if not quarantined.empty else 0,
        "conflicting_duplicate_ids": int(len(conflicting_ids)),
    }
    write_json(reports_dir / "duplicate_report.json", duplicate_report)
    cat_rows = []
    for raw_col in NORMALIZED_TEXT_COLUMNS + ["validation_status"]:
        norm_col = f"{raw_col}_normalized"
        if raw_col == "validation_status":
            norm_col = "validation_status_normalized"
        if raw_col in work and norm_col in work:
            cat_rows.append({
                "column": raw_col,
                "normalized_column": norm_col,
                "raw_unique_count": int(work[raw_col].nunique(dropna=True)),
                "normalized_unique_count": int(work[norm_col].nunique(dropna=True)),
                "raw_null_like_count": int(work[raw_col].map(lambda v: is_null_like(v, null_tokens)).sum()),
                "normalized_null_count": int(work[norm_col].isna().sum()),
                "normalization": "NFKC + trim + whitespace collapse + uppercase aliases where applicable",
                "notes": "",
            })
    if "data_sent_to_scita" in work:
        cat_rows.append({
            "column": "data_sent_to_scita",
            "normalized_column": "data_sent_to_scita_boolean",
            "raw_unique_count": int(work["data_sent_to_scita"].nunique(dropna=True)),
            "normalized_unique_count": int(work["data_sent_to_scita_boolean"].nunique(dropna=True)),
            "raw_null_like_count": int(work["data_sent_to_scita"].map(lambda v: is_null_like(v, null_tokens)).sum()),
            "normalized_null_count": int(work["data_sent_to_scita_boolean"].isna().sum()),
            "normalization": "explicit boolean aliases true/false/1/0/yes/no/y/n",
            "notes": "unknown raw values: " + json.dumps(unknown_bool, ensure_ascii=True),
        })
    pd.DataFrame(cat_rows).to_csv(reports_dir / "category_normalization_report.csv", index=False)

    raw_rows = int(len(raw))
    reconciliation_passed = raw_rows == len(accepted) + len(quarantined) + len(exact_duplicates)
    reconciliation = {
        "raw_rows": raw_rows,
        "accepted_rows": int(len(accepted)),
        "quarantined_rows": int(len(quarantined)),
        "exact_duplicate_rows_removed": int(len(exact_duplicates)),
        "equation": "raw rows = clean accepted rows + quarantined rows + exact duplicate copies removed",
        "passed": bool(reconciliation_passed),
    }
    write_json(reports_dir / "row_reconciliation.json", reconciliation)

    valid_violation = accepted["violation_label_count"] > 0
    parking_related = int((valid_violation & accepted["contains_parking_related_label"]).sum())
    non_parking = int((valid_violation & ~accepted["contains_parking_related_label"]).sum())
    parking_summary = {
        "parking_related_records": parking_related,
        "non_parking_records": non_parking,
        "unmapped_records": int(non_parking),
        "parking_related_percentage": round(100 * parking_related / int(valid_violation.sum()), 4) if int(valid_violation.sum()) else 0.0,
        "classification_method": "explicit versioned label set in configs/phase1.yaml",
    }

    repeat = _repeat_summary(accepted)
    validation = _validation_summary(accepted)
    temporal = _temporal_artifact_report(accepted)
    claims = _claims_comparison(accepted, raw_rows, len(quarantined), len(exact_duplicates),
                                config, repeat, validation, temporal, parking_summary)

    write_json(reports_dir / "repeat_offender_summary.json", repeat)
    write_json(reports_dir / "validation_summary.json", validation)
    write_json(reports_dir / "temporal_artifact_report.json", temporal)
    capability = _capability_limitations(accepted)
    capability.to_csv(reports_dir / "capability_limitations.csv", index=False)
    claims.to_csv(reports_dir / "document_claims_comparison.csv", index=False)

    rows_with_unmapped = int(((work["violation_label_count"] > 0) & (~work["contains_parking_related_label"])).sum())
    cleaning_report = {
        "input_rows": raw_rows,
        "accepted_rows": int(len(accepted)),
        "quarantined_rows": int(len(quarantined)),
        "exact_duplicate_rows_removed": int(len(exact_duplicates)),
        "conflicting_duplicate_id_rows": duplicate_report["conflicting_duplicate_id_rows"],
        "invalid_coordinate_rows": int((~work["coordinate_global_valid"]).sum()),
        "invalid_created_datetime_rows": int((~work["created_datetime_parse_valid"]).sum()),
        "missing_id_rows": int(work["id"].map(lambda v: is_null_like(v, null_tokens)).sum()),
        "missing_device_id_rows": int(work["device_id"].map(lambda v: is_null_like(v, null_tokens)).sum()),
        "outside_bengaluru_flagged_rows": int(len(outside)),
        "possible_coordinate_swap_rows": int(work["possible_coordinate_swap"].sum()),
        "rows_with_unmapped_violation_labels": rows_with_unmapped,
        "rows_with_unparsed_offence_codes": int((~work["offence_code_parse_valid"]).sum()),
        "row_reconciliation_passed": bool(reconciliation_passed),
    }
    write_json(reports_dir / "cleaning_report.json", cleaning_report)
    write_json(reports_dir / "cleaned_profile.json", {
        "row_count": int(len(accepted)),
        "column_count": int(len(accepted.columns)),
        "dataset_fingerprint": dataframe_fingerprint(accepted),
    })

    derived = [c for c in accepted.columns if c not in source_cols]
    data_dictionary(source_cols, derived).to_csv(reports_dir / "data_dictionary.csv", index=False)

    raw_null_path = reports_dir / "raw_null_report.csv"
    plots = []
    if raw_null_path.exists():
        raw_null = pd.read_csv(raw_null_path)
        plots = _plots(accepted, raw_null, reports_dir.parent / "plots")

    reports = {
        "cleaning_report": cleaning_report,
        "row_reconciliation": reconciliation,
        "repeat_offender_summary": repeat,
        "validation_summary": validation,
        "temporal_artifact_report": temporal,
        "parking_summary": parking_summary,
        "plots": plots,
    }
    return Phase1CleanResult(
        accepted=accepted,
        quarantined=quarantined,
        exact_duplicates=exact_duplicates,
        reports=reports,
        output_columns=list(accepted.columns),
    )
