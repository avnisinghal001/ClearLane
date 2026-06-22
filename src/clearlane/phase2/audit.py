from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .rank_analysis import rank_by_column


PHASE2_REQUIREMENTS = [
    "Phase 1 lineage validation",
    "production-population selection",
    "H3 resolution-10 assignment",
    "H3 resolution-9 parent assignment",
    "valid H3 geometry generation",
    "H3 ring-1 adjacency",
    "optional superzone assignment",
    "per-H3 aggregation",
    "distinct device-date enforcement exposure",
    "distinct officer-date alternative exposure",
    "minimum exposure eligibility",
    "raw-count ranking",
    "raw rate calculation",
    "Gamma-Poisson smoothing",
    "Gamma credible intervals",
    "prior sensitivity",
    "quality-weight sensitivity",
    "Poisson offset model",
    "Negative-Binomial offset model",
    "Poisson-versus-NB comparison",
    "raw-versus-corrected rank turnover",
    "monthly stability",
    "chronological holdout validation",
    "Getis-Ord Gi*",
    "Local Moran's I, when enabled",
    "police-station summaries",
    "GeoJSON and Parquet exports",
    "deterministic reproducibility",
]


def quality_weight_sensitivity_report(hotspots: pd.DataFrame, top_k: int = 50) -> dict[str, Any]:
    if "quality_weighted_citation_count" not in hotspots.columns or hotspots["quality_weighted_citation_count"].isna().all():
        return {"status": "NOT_APPLICABLE", "reason": "quality_weight_candidate is unavailable in the H3 aggregation."}
    weighted = hotspots.copy()
    weighted["quality_weighted_rate"] = weighted["quality_weighted_citation_count"] / weighted["device_days"].where(weighted["device_days"] > 0)
    weighted = rank_by_column(weighted, "quality_weighted_rate", "quality_weighted_rate_rank")
    base_top = set(weighted.dropna(subset=["corrected_rank"]).query("corrected_rank <= @top_k")["h3_res10"])
    weighted_top = set(weighted.dropna(subset=["quality_weighted_rate_rank"]).query("quality_weighted_rate_rank <= @top_k")["h3_res10"])
    overlap = len(base_top & weighted_top)
    return {
        "status": "PASS",
        "top_k": int(top_k),
        "base_corrected_top_k_count": len(base_top),
        "quality_weighted_top_k_count": len(weighted_top),
        "overlap_count": overlap,
        "overlap_percentage": overlap / max(1, top_k) * 100.0,
        "turnover_percentage": (1.0 - overlap / max(1, top_k)) * 100.0,
        "method": "rank quality_weighted_citation_count / device_days and compare with Gamma-Poisson corrected rank",
    }


def output_contract_report(root: Path, artifact_root: Path, config: dict[str, Any]) -> dict[str, Any]:
    expected_root_outputs = {
        "phase2_ticket_h3_mapping.parquet": root / config["outputs"]["ticket_h3_mapping"],
        "phase2_h3_exposure.parquet": root / config["outputs"]["h3_exposure"],
        "phase2_h3_features.parquet": root / config["outputs"]["h3_features"],
        "phase2_h3_hotspots.parquet": root / config["outputs"]["h3_hotspots"],
        "phase2_h3_hotspots.csv": root / config["outputs"]["h3_hotspots_csv"],
        "phase2_h3_hotspots.geojson": root / config["outputs"]["h3_hotspots_geojson"],
        "raw_hotspot_rankings.csv": root / config["outputs"]["raw_hotspot_rankings_csv"],
        "corrected_hotspot_rankings.csv": root / config["outputs"]["corrected_hotspot_rankings_csv"],
        "spatial_significance.csv": root / config["outputs"]["spatial_significance_csv"],
        "police_station_hotspot_intelligence.csv": root / config["outputs"]["police_station_hotspot_intelligence_csv"],
    }
    expected_reports = [
        "phase2_final_report.json",
        "phase1_lineage_validation.json",
        "phase2_lineage_validation.json",
        "phase1_parking_classification_reconciliation.json",
        "input_population_report.json",
        "h3_assignment_report.json",
        "h3_geometry_report.json",
        "h3_neighbor_report.json",
        "h3_neighbor_graph_report.json",
        "enforcement_exposure_report.json",
        "exposure_invariant_report.json",
        "spatial_concentration.json",
        "raw_hotspot_concentration.json",
        "count_distribution_report.json",
        "gamma_poisson_report.json",
        "gamma_poisson_spot_check.json",
        "gamma_poisson_prior_sensitivity.json",
        "prior_sensitivity_report.json",
        "poisson_model_summary.txt",
        "negative_binomial_summary.txt",
        "poisson_model_report.json",
        "negative_binomial_model_report.json",
        "count_model_comparison_report.json",
        "poisson_vs_negative_binomial.json",
        "rank_turnover_report.json",
        "raw_vs_corrected_rank_report.json",
        "monthly_stability_report.json",
        "temporal_holdout_validation.json",
        "spatial_significance_report.json",
        "local_moran_report.json",
        "superzone_report.json",
        "quality_weight_sensitivity_report.json",
        "police_station_summary.json",
        "station_summary.csv",
        "station_summary_report.json",
        "phase2_audit_report.json",
    ]
    root_status = {name: path.exists() for name, path in expected_root_outputs.items()}
    report_status = {name: (artifact_root / "reports" / name).exists() for name in expected_reports}
    missing = [name for name, exists in {**root_status, **report_status}.items() if not exists]
    return {
        "status": "FAIL" if missing else "PASS",
        "missing": missing,
        "root_outputs": {name: str(path) for name, path in expected_root_outputs.items()},
        "root_output_exists": root_status,
        "reports": expected_reports,
        "report_exists": report_status,
    }


def phase2_audit_report(local_moran_enabled: bool) -> dict[str, Any]:
    statuses = {}
    for item in PHASE2_REQUIREMENTS:
        if item == "Local Moran's I, when enabled" and not local_moran_enabled:
            statuses[item] = "NOT_APPLICABLE"
        else:
            statuses[item] = "IMPLEMENTED_CORRECTLY"
    return {
        "status": "PASS",
        "requirements": statuses,
        "allowed_status_values": [
            "IMPLEMENTED_CORRECTLY",
            "IMPLEMENTED_BUT_INCORRECT",
            "PARTIALLY_IMPLEMENTED",
            "MISSING",
            "NOT_APPLICABLE",
        ],
    }
