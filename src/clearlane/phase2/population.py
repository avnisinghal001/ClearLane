from __future__ import annotations

from typing import Any

import pandas as pd


ALL_ACCEPTED = "population_all_accepted"
PARKING_CLASSIFIED = "population_parking_classified"


def _claim_value(document_claims: list[dict[str, Any]], claim_name: str,
                 column: str = "document_reference_value") -> Any:
    for row in document_claims:
        if row.get("claim_name") == claim_name:
            return row.get(column)
    return None


def parking_classification_reconciliation(
    df: pd.DataFrame,
    phase1_final_report: dict[str, Any],
    document_claims: list[dict[str, Any]],
    production_population: str,
) -> dict[str, Any]:
    if "contains_parking_related_label" not in df.columns:
        raise ValueError("contains_parking_related_label is required for population reconciliation.")

    parking_mask = df["contains_parking_related_label"].fillna(False).astype(bool)
    parking_count = int(parking_mask.sum())
    unknown_count = int(df["contains_parking_related_label"].isna().sum())
    non_parking_count = int((~parking_mask).sum() - unknown_count)
    total = int(len(df))
    recomputed_pct = round((parking_count / total) * 100, 4) if total else 0.0
    phase1_summary = phase1_final_report.get("summary", {})
    phase1_pct = phase1_summary.get("parking_related_percentage")
    document_pct = _claim_value(document_claims, "parking_related_percentage")

    try:
        document_pct_numeric = float(document_pct) if document_pct is not None and str(document_pct) != "" else None
    except (TypeError, ValueError):
        document_pct_numeric = None
    discrepancy = document_pct_numeric is not None and document_pct_numeric != recomputed_pct
    return {
        "status": "WARN" if discrepancy else "PASS",
        "warnings": ["PARKING_CLASSIFICATION_DISCREPANCY"] if discrepancy else [],
        "production_population": production_population,
        "denominator_definition": "Phase 1 accepted rows",
        "classification_mapping_version": "phase1.violation_labels.parking_related from configs/phase1.yaml",
        "populations": {
            ALL_ACCEPTED: {
                "rows": total,
                "description": "All Phase 1 accepted rows.",
            },
            PARKING_CLASSIFIED: {
                "rows": parking_count,
                "description": "Rows with contains_parking_related_label == true.",
            },
            "population_non_parking": {
                "rows": non_parking_count,
                "description": "Rows with contains_parking_related_label == false.",
            },
            "population_unknown_parking_classification": {
                "rows": unknown_count,
                "description": "Rows with missing parking classification.",
            },
        },
        "parking_related_percentage_recomputed": recomputed_pct,
        "parking_related_percentage_phase1_reported": phase1_pct,
        "parking_related_percentage_document_reference": document_pct,
        "document_discrepancy_policy": (
            "Do not filter records to reproduce the document claim. Keep both "
            "populations and use configs/phase2.yaml to choose production scope."
        ),
        "difference_explanation": (
            "Phase 2 trusts the Phase 1 recomputation from normalized violation labels. "
            "The older 97.3% document value is retained as a reference discrepancy, "
            "not as a filtering rule."
        ),
    }


def select_population(df: pd.DataFrame, population_name: str) -> pd.DataFrame:
    if population_name == ALL_ACCEPTED:
        out = df.copy()
        out["phase2_population"] = ALL_ACCEPTED
        return out
    if population_name == PARKING_CLASSIFIED:
        if "contains_parking_related_label" not in df.columns:
            raise ValueError("contains_parking_related_label is required for parking-classified population.")
        out = df[df["contains_parking_related_label"].fillna(False).astype(bool)].copy()
        out["phase2_population"] = PARKING_CLASSIFIED
        return out
    raise ValueError(f"Unknown Phase 2 population: {population_name}")


def population_report(df: pd.DataFrame, production_population: str) -> dict[str, Any]:
    selected = select_population(df, production_population)
    return {
        "status": "PASS",
        "production_population": production_population,
        "accepted_rows": int(len(df)),
        "production_rows": int(len(selected)),
        "rows_removed_by_population_filter": int(len(df) - len(selected)),
    }
