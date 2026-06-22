from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from .audit import (
    output_contract_report,
    phase2_audit_report,
    quality_weight_sensitivity_report,
)
from .aggregation import aggregate_h3, count_distribution_report
from .count_models import (
    build_count_model_frame,
    fit_negative_binomial_offset,
    fit_poisson_offset,
    model_comparison,
    overdispersion_report,
    validate_model_report,
)
from .exposure import (
    attach_exposure,
    compute_exposure,
    exposure_invariant_report,
    independent_exposure_check,
)
from .export import write_hotspot_geojson, write_json, write_table
from .gamma_poisson import fit_gamma_poisson, gamma_poisson_spot_check, prior_sensitivity
from .h3_assignment import assign_h3_cells, h3_assignment_report
from .h3_geometry import geometry_table
from .lineage import (
    LineageError,
    config_hash,
    git_commit,
    load_config,
    make_run_id,
    python_environment_report,
    repo_root,
    validate_phase1_lineage,
)
from .population import (
    parking_classification_reconciliation,
    population_report,
    select_population,
)
from .rank_analysis import rank_turnover
from .raw_baseline import concentration_report, rank_raw_hotspots
from .spatial_significance import compute_gistar, local_moran_disabled_report
from .spatial_weights import component_table, neighbor_report
from .station_intelligence import station_report, station_summary
from .superzone_mapping import superzone_status
from .temporal_validation import chronological_holdout_validation, monthly_stability_report


def _resolve(root: Path, value: str | Path) -> Path:
    p = Path(value)
    return p if p.is_absolute() else root / p


def _artifact_dirs(root: Path, config: dict[str, Any], run_id: str) -> tuple[Path, Path]:
    artifact_root = _resolve(root, config["outputs"]["artifact_root"]) / run_id
    reports_dir = artifact_root / "reports"
    for child in (reports_dir, artifact_root / "logs", artifact_root / "plots", artifact_root / "models"):
        child.mkdir(parents=True, exist_ok=True)
    return artifact_root, reports_dir


def _manifest_base(config: dict[str, Any], run_id: str,
                   artifact_root: Path, started_at: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "phase": "phase2",
        "status": "running",
        "started_at": started_at,
        "completed_at": None,
        "artifact_dir": str(artifact_root),
        "config_path": config["_config_path"],
        "config_sha256": config_hash(config["_config_path"]),
        "git_commit": git_commit(),
        "python_environment": python_environment_report(),
        "phase1": {},
        "loaded_rows": None,
        "production_population": config["population"]["production_population"],
        "h3_resolution": config["spatial"]["resolution"],
        "minimum_device_days": config["exposure"]["minimum_device_days"],
        "forbidden_inputs_used": [],
        "errors": [],
        "warnings": [],
    }


def _write_failure(reports_dir: Path, manifest: dict[str, Any],
                   errors: list[str], warnings: list[str], started: float) -> dict[str, Any]:
    manifest["status"] = "FAIL"
    manifest["errors"] = errors
    manifest["warnings"] = warnings
    manifest["completed_at"] = datetime.now(ZoneInfo("Asia/Kolkata")).isoformat()
    final = {
        "run_id": manifest["run_id"],
        "status": "FAIL",
        "errors": errors,
        "warnings": warnings,
        "duration_seconds": round(time.time() - started, 3),
    }
    write_json(reports_dir / "phase2_final_report.json", final)
    write_json(Path(manifest["artifact_dir"]) / "manifest.json", manifest)
    return final


def _add_warnings(target: list[str], values: list[str] | None) -> None:
    for value in values or []:
        if value not in target:
            target.append(value)


def run_phase2(config_path: str | Path = "configs/phase2.yaml",
               root: str | Path | None = None,
               lineage_only: bool = False,
               skip_models: bool = False) -> dict[str, Any]:
    root_path = repo_root(root)
    config = load_config(config_path, root_path)
    run_id = make_run_id("phase2")
    started_at = datetime.now(ZoneInfo("Asia/Kolkata")).isoformat()
    started = time.time()
    artifact_root, reports_dir = _artifact_dirs(root_path, config, run_id)
    manifest = _manifest_base(config, run_id, artifact_root, started_at)
    write_json(artifact_root / "manifest.json", manifest)

    errors: list[str] = []
    warnings: list[str] = []

    try:
        lineage = validate_phase1_lineage(config, root_path)
        lineage_report = lineage.to_report()
        write_json(reports_dir / "phase2_lineage_validation.json", lineage_report)
        write_json(reports_dir / "phase1_lineage_validation.json", lineage_report)
        manifest["phase1"] = {
            "run_id": lineage.phase1_run_id,
            "artifact_dir": str(lineage.artifact_dir),
            "cleaned_parquet": str(lineage.cleaned_parquet),
            "cleaned_parquet_sha256": lineage.cleaned_parquet_sha256,
            "checksum_source": lineage.checksum_source,
            "accepted_rows": lineage.expected_rows,
        }
        manifest["loaded_rows"] = lineage.loaded_rows

        df = pd.read_parquet(lineage.cleaned_parquet)
        production_population = config["population"]["production_population"]
        population_reconciliation = parking_classification_reconciliation(
            df,
            lineage.phase1_final_report,
            lineage.document_claims,
            production_population,
        )
        _add_warnings(warnings, population_reconciliation.get("warnings"))
        write_json(
            reports_dir / "phase1_parking_classification_reconciliation.json",
            population_reconciliation,
        )
        write_json(reports_dir / "input_population_report.json", population_report(df, production_population))

        if lineage_only:
            final_status = "PASS"
            final = {
                "run_id": run_id,
                "status": final_status,
                "mode": "lineage_only",
                "errors": errors,
                "warnings": warnings,
                "duration_seconds": round(time.time() - started, 3),
                "artifact_dir": str(artifact_root),
            }
            manifest["status"] = final_status
            manifest["completed_at"] = datetime.now(ZoneInfo("Asia/Kolkata")).isoformat()
            write_json(reports_dir / "phase2_final_report.json", final)
            write_json(artifact_root / "manifest.json", manifest)
            return final

        selected = select_population(df, production_population)
        mapping = assign_h3_cells(
            selected,
            resolution=config["spatial"]["resolution"],
            parent_resolution=config["spatial"]["parent_resolution"],
        )
        write_table(mapping, _resolve(root_path, config["outputs"]["ticket_h3_mapping"]))
        h3_report = h3_assignment_report(
            len(selected),
            mapping,
            config["spatial"]["resolution"],
            config["spatial"]["parent_resolution"],
        )
        write_json(reports_dir / "h3_assignment_report.json", h3_report)
        if h3_report["status"] != "PASS":
            errors.extend(h3_report["failures"])

        aggregates = aggregate_h3(mapping)
        exposure = compute_exposure(
            mapping,
            minimum_device_days=config["exposure"]["minimum_device_days"],
        )
        write_table(exposure, _resolve(root_path, config["outputs"]["h3_exposure"]))
        invariant_report = exposure_invariant_report(exposure, aggregates)
        write_json(reports_dir / "exposure_invariant_report.json", invariant_report)
        independent_exposure = independent_exposure_check(
            mapping,
            exposure,
            minimum_device_days=config["exposure"]["minimum_device_days"],
        )
        enforcement_report = {
            **invariant_report,
            "independent_recompute": independent_exposure,
            "primary_exposure": "distinct(device_id, created_date) per H3",
            "alternative_exposure": "distinct(created_by_id, created_date) per H3",
        }
        write_json(reports_dir / "enforcement_exposure_report.json", enforcement_report)
        if invariant_report["status"] != "PASS":
            errors.extend(invariant_report["failures"])
        if independent_exposure["status"] != "PASS":
            errors.extend(independent_exposure["failures"])

        hot = attach_exposure(aggregates, exposure)
        hot = rank_raw_hotspots(hot)
        raw_concentration = concentration_report(
            hot,
            percentiles=config["raw_baseline"]["concentration_percentiles"],
        )
        write_json(reports_dir / "raw_hotspot_concentration.json", raw_concentration)
        write_json(reports_dir / "spatial_concentration.json", raw_concentration)
        write_json(reports_dir / "count_distribution_report.json", count_distribution_report(hot))

        hot, gp_report = fit_gamma_poisson(
            hot,
            prior_strength=config["gamma_poisson"]["prior_strength"],
            credible_interval=config["gamma_poisson"]["credible_interval"],
        )
        write_json(reports_dir / "gamma_poisson_report.json", gp_report)
        if gp_report["status"] != "PASS":
            errors.extend(gp_report.get("failures", []))
        sensitivity_report = prior_sensitivity(
            hot,
            prior_strengths=config["gamma_poisson"]["sensitivity_prior_strengths"],
            top_k=config["gamma_poisson"]["sensitivity_top_k"],
            base_prior_strength=config["gamma_poisson"]["prior_strength"],
        )
        write_json(reports_dir / "gamma_poisson_prior_sensitivity.json", sensitivity_report)
        write_json(reports_dir / "prior_sensitivity_report.json", sensitivity_report)
        write_json(
            reports_dir / "gamma_poisson_spot_check.json",
            gamma_poisson_spot_check(hot, seed=config["project"]["random_seed"]),
        )
        rank_report = rank_turnover(hot, hot, top_k_values=config["raw_baseline"]["top_k_values"])
        write_json(reports_dir / "rank_turnover_report.json", rank_report)
        write_json(reports_dir / "raw_vs_corrected_rank_report.json", rank_report)

        cells = list(hot["h3_res10"].astype(str))
        neighbors = neighbor_report(cells, config["spatial_significance"]["minimum_present_neighbors"])
        write_json(reports_dir / "h3_neighbor_graph_report.json", neighbors)
        write_json(reports_dir / "h3_neighbor_report.json", neighbors)
        _add_warnings(warnings, neighbors.get("warnings"))
        hot = hot.merge(
            component_table(cells, config["spatial_significance"]["minimum_present_neighbors"]),
            on="h3_res10",
            how="left",
        )

        if config["spatial_significance"].get("enabled", True):
            hot, gistar_report = compute_gistar(
                hot,
                neighbors["neighbors"],
                minimum_component_size=config["spatial_significance"]["minimum_component_size"],
                permutations=config["spatial_significance"]["permutations"],
                seed=config["spatial_significance"]["random_seed"],
                weight_transform=config["spatial_significance"]["weight_transform"],
                include_self=config["spatial_significance"]["include_self_for_gistar"],
            )
            write_json(reports_dir / "spatial_significance_report.json", gistar_report)
            _add_warnings(warnings, gistar_report.get("warnings"))
        write_json(
            reports_dir / "local_moran_report.json",
            local_moran_disabled_report(config["spatial_significance"].get("local_moran_enabled", False)),
        )

        geo = geometry_table(hot["h3_res10"])
        hot = hot.merge(geo, on="h3_res10", how="left")
        if not hot["polygon_valid"].fillna(False).all():
            errors.append("One or more H3 polygons failed geometry validation.")
        write_json(reports_dir / "h3_geometry_report.json", {
            "status": "FAIL" if not hot["polygon_valid"].fillna(False).all() else "PASS",
            "cell_count": int(len(hot)),
            "invalid_polygon_count": int((~hot["polygon_valid"].fillna(False)).sum()),
            "crs": "EPSG:4326",
        })

        write_json(reports_dir / "superzone_report.json", superzone_status(config, root_path))
        station = station_summary(mapping)
        station.to_csv(artifact_root / "reports" / "station_summary.csv", index=False)
        station_csv = _resolve(root_path, config["outputs"]["police_station_hotspot_intelligence_csv"])
        station_csv.parent.mkdir(parents=True, exist_ok=True)
        station.to_csv(station_csv, index=False)
        write_json(reports_dir / "station_summary_report.json", station_report(station))
        write_json(reports_dir / "police_station_summary.json", station_report(station))

        if config["negative_binomial"].get("fit_enabled", True) and not skip_models:
            model_input = hot[hot["eligible_for_corrected_ranking"].fillna(False).astype(bool)].copy()
            dispersion = overdispersion_report(model_input)
            write_json(reports_dir / "count_model_overdispersion_report.json", dispersion)
            frame = build_count_model_frame(model_input, config["negative_binomial"]["feature_columns"])
            poisson_result, poisson = fit_poisson_offset(frame)
            nb_result, nb = fit_negative_binomial_offset(frame, maxiter=config["negative_binomial"].get("maxiter", 200))
            (reports_dir / "poisson_model_summary.txt").write_text(poisson_result.summary().as_text() + "\n", encoding="utf-8")
            (reports_dir / "negative_binomial_summary.txt").write_text(nb_result.summary().as_text() + "\n", encoding="utf-8")
            nb_pred = nb_result.predict(exog=frame.x, offset=frame.offset)
            hot.loc[frame.y.index, "nb_predicted_count"] = nb_pred
            hot.loc[frame.y.index, "nb_predicted_rate"] = nb_pred / model_input.loc[frame.y.index, "device_days"].astype(float)
            hot = hot.sort_values("h3_res10").reset_index(drop=True)
            ranked_nb = hot.dropna(subset=["nb_predicted_rate"]).sort_values(["nb_predicted_rate", "h3_res10"], ascending=[False, True])
            hot["nb_predicted_rate_rank"] = pd.NA
            hot.loc[ranked_nb.index, "nb_predicted_rate_rank"] = range(1, len(ranked_nb) + 1)
            write_json(reports_dir / "poisson_model_report.json", poisson)
            write_json(reports_dir / "negative_binomial_model_report.json", nb)
            model_failures = validate_model_report(poisson) + validate_model_report(nb)
            if model_failures:
                errors.extend(model_failures)
            comparison = model_comparison(poisson, nb, dispersion)
            if comparison["status"] != "PASS":
                errors.append("Poisson-vs-NB model comparison failed.")
            write_json(reports_dir / "count_model_comparison_report.json", comparison)
            write_json(reports_dir / "poisson_vs_negative_binomial.json", comparison)
        elif skip_models:
            warnings.append("Count model fitting skipped by caller.")

        table_hot = hot.drop(columns=["geometry_geojson"], errors="ignore")
        write_table(table_hot, _resolve(root_path, config["outputs"]["h3_features"]))
        table_hot.sort_values(["raw_rank", "h3_res10"]).to_csv(_resolve(root_path, config["outputs"]["raw_hotspot_rankings_csv"]), index=False)
        table_hot.dropna(subset=["corrected_rank"]).sort_values(["corrected_rank", "h3_res10"]).to_csv(
            _resolve(root_path, config["outputs"]["corrected_hotspot_rankings_csv"]),
            index=False,
        )
        spatial_cols = [
            c for c in [
                "h3_res10",
                "spatial_component_id",
                "spatial_component_size",
                "present_neighbor_count",
                "is_spatial_island",
                "spatial_test_status",
                "gistar_z_score",
                "gistar_p_value",
                "gistar_q_value",
                "spatial_hotspot_label",
            ] if c in table_hot.columns
        ]
        table_hot[spatial_cols].to_csv(_resolve(root_path, config["outputs"]["spatial_significance_csv"]), index=False)
        write_table(
            table_hot,
            _resolve(root_path, config["outputs"]["h3_hotspots"]),
            _resolve(root_path, config["outputs"]["h3_hotspots_csv"]),
        )
        write_hotspot_geojson(table_hot, _resolve(root_path, config["outputs"]["h3_hotspots_geojson"]))
        write_json(reports_dir / "quality_weight_sensitivity_report.json", quality_weight_sensitivity_report(table_hot))
        write_json(
            reports_dir / "monthly_stability_report.json",
            monthly_stability_report(
                mapping,
                config["exposure"]["minimum_device_days"],
                config["gamma_poisson"]["prior_strength"],
                config["stability"]["monthly_top_k_values"],
            ),
        )
        write_json(
            reports_dir / "temporal_holdout_validation.json",
            chronological_holdout_validation(
                mapping,
                config["exposure"]["minimum_device_days"],
                config["gamma_poisson"]["prior_strength"],
                config["raw_baseline"]["top_k_values"],
                train_fraction=config["stability"]["holdout_train_fraction"],
            ),
        )
        write_json(
            reports_dir / "phase2_audit_report.json",
            phase2_audit_report(config["spatial_significance"].get("local_moran_enabled", False)),
        )

        final_status = "FAIL" if errors else ("WARN" if warnings else "PASS")
        final = {
            "run_id": run_id,
            "status": final_status,
            "errors": errors,
            "warnings": warnings,
            "duration_seconds": round(time.time() - started, 3),
            "artifact_dir": str(artifact_root),
            "outputs": {
                "ticket_h3_mapping": str(_resolve(root_path, config["outputs"]["ticket_h3_mapping"])),
                "h3_exposure": str(_resolve(root_path, config["outputs"]["h3_exposure"])),
                "h3_features": str(_resolve(root_path, config["outputs"]["h3_features"])),
                "h3_hotspots": str(_resolve(root_path, config["outputs"]["h3_hotspots"])),
                "h3_hotspots_csv": str(_resolve(root_path, config["outputs"]["h3_hotspots_csv"])),
                "h3_hotspots_geojson": str(_resolve(root_path, config["outputs"]["h3_hotspots_geojson"])),
                "raw_hotspot_rankings_csv": str(_resolve(root_path, config["outputs"]["raw_hotspot_rankings_csv"])),
                "corrected_hotspot_rankings_csv": str(_resolve(root_path, config["outputs"]["corrected_hotspot_rankings_csv"])),
                "spatial_significance_csv": str(_resolve(root_path, config["outputs"]["spatial_significance_csv"])),
                "police_station_hotspot_intelligence_csv": str(_resolve(root_path, config["outputs"]["police_station_hotspot_intelligence_csv"])),
            },
        }
        manifest["status"] = final_status
        manifest["errors"] = errors
        manifest["warnings"] = warnings
        manifest["completed_at"] = datetime.now(ZoneInfo("Asia/Kolkata")).isoformat()
        write_json(reports_dir / "phase2_final_report.json", final)
        contract = output_contract_report(root_path, artifact_root, config)
        write_json(reports_dir / "output_contract_report.json", contract)
        if contract["status"] != "PASS":
            errors.append("Output contract is incomplete: " + ", ".join(contract["missing"]))
            final_status = "FAIL"
            final["status"] = final_status
            final["errors"] = errors
            manifest["status"] = final_status
            manifest["errors"] = errors
            write_json(reports_dir / "phase2_final_report.json", final)
        write_json(artifact_root / "manifest.json", manifest)
        return final
    except LineageError as exc:
        return _write_failure(reports_dir, manifest, exc.errors, warnings, started)
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
        return _write_failure(reports_dir, manifest, errors, warnings, started)
