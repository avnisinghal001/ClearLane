"""Phase 3 runner — orchestrates every CLI mode.

Modes: lineage-only, select-candidates, capability-probe, prepare-segments,
poll-once, collect, replay. Each mode writes an artifact run directory with
reports and (where applicable) dashboard outputs, propagates Phase 2 allowed
warnings transparently, and never claims citywide live coverage or direct
parked-car detection.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from . import baselines as bl
from . import candidate_selection as cs
from . import capability_probe as cap
from . import confidence as conf
from . import exports
from . import lineage as lineage_mod
from . import region_validation as region
from . import reporting
from . import schema
from .api_budget import ApiBudget, BudgetExceeded
from .common import (
    load_config,
    make_run_id,
    now_ist,
    redact,
    repo_root,
    sha256_file,
    write_json,
)
from .mappls_auth import load_credentials
from .mappls_client import LIVE, REPLAY, MapplsClient
from .segment_builder import build_segment_for_h3

ALLOWED_WARNINGS = {
    "PHASE2_ALLOWED_WARNINGS_PROPAGATED",
    "OPTIONAL_REVERSE_GEOCODE_UNAVAILABLE",
    "OPTIONAL_SNAP_TO_ROAD_UNAVAILABLE",
    "NATIVE_TRAFFIC_TILES_UNAVAILABLE",
    "PREDICTIVE_TRAFFIC_UNAVAILABLE",
    "PROVISIONAL_BASELINES_USED",
    "BASELINE_COLD_START",
    "PARTIAL_SEGMENT_COVERAGE",
    "PARTIAL_LIVE_OBSERVATION_COVERAGE",
    "ONE_DIRECTION_ONLY",
    "LOCALIZED_ANOMALY_INSUFFICIENT_NEIGHBORS",
    "ROUTE_ETA_FALLBACK_USED",
}


@dataclass
class RunContext:
    config: dict[str, Any]
    root: Path
    run_id: str
    artifact_dir: Path
    reports_dir: Path
    data_mode: str
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    outputs: dict[str, str] = field(default_factory=dict)

    def report(self, name: str, payload: Any) -> None:
        write_json(self.reports_dir / name, payload)

    def warn(self, code: str) -> None:
        if code not in self.warnings:
            self.warnings.append(code)


def _abs(root: Path, rel: str) -> Path:
    return root / rel


def _new_context(config: dict[str, Any], root: Path, mode: str, data_mode: str) -> RunContext:
    run_id = make_run_id("phase3")
    artifact_dir = _abs(root, config["outputs"]["artifact_root"]) / run_id
    reports_dir = artifact_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    config["_run_id"] = run_id
    return RunContext(
        config=config,
        root=root,
        run_id=run_id,
        artifact_dir=artifact_dir,
        reports_dir=reports_dir,
        data_mode=data_mode,
    )


# --------------------------------------------------------------------------- #
# Stage 1 — lineage                                                            #
# --------------------------------------------------------------------------- #
def _run_lineage(ctx: RunContext) -> lineage_mod.Phase2Lineage:
    lin = lineage_mod.validate(ctx.config, ctx.root)
    ctx.report("phase2_lineage_validation.json", lin.to_report())
    ctx.report("input_schema_report.json", schema.schema_report(lin.hotspots))
    # propagate phase 2 warnings transparently
    if lin.phase2_warnings:
        ctx.warn("PHASE2_ALLOWED_WARNINGS_PROPAGATED")
    return lin


# --------------------------------------------------------------------------- #
# Stage 2 — candidate selection + region validation                           #
# --------------------------------------------------------------------------- #
def _run_candidates(
    ctx: RunContext,
    lin: lineage_mod.Phase2Lineage,
    *,
    client: Optional[MapplsClient] = None,
    reverse_geocode: bool = False,
) -> pd.DataFrame:
    counts = cs.selection_counts(lin.hotspots, ctx.config)
    selected = cs.select_candidates(lin.hotspots, ctx.config)

    # optional reverse-geocode enrichment of PRIMARY cells
    rg_map: dict[str, dict[str, Any]] = {}
    rg_unavailable = False
    if reverse_geocode and client is not None:
        from .reverse_geocode_adapter import call_reverse_geocode

        primaries = selected[selected["candidate_tier"] == "PRIMARY"]
        for _, r in primaries.iterrows():
            try:
                res, _ = call_reverse_geocode(
                    client, float(r["centroid_latitude"]), float(r["centroid_longitude"])
                )
                rg_map[str(r["h3_res10"])] = {
                    "locality": res.locality,
                    "subLocality": res.sub_locality,
                    "formatted_address": res.formatted_address,
                }
            except Exception:
                rg_unavailable = True
    if rg_unavailable:
        ctx.warn("OPTIONAL_REVERSE_GEOCODE_UNAVAILABLE")

    validated = region.validate_candidates(selected, ctx.config, rg_map or None)
    validated["historical_station"] = validated["mode_police_station"]
    validated["phase2_run_id"] = lin.phase2_run_id
    validated["phase3_run_id"] = ctx.run_id
    validated["generated_at"] = now_ist().isoformat()

    out_cols = [
        "h3_res10", "centroid_latitude", "centroid_longitude",
        "historical_station", "mode_police_station", "citation_count", "device_days",
        "normalized_propensity", "corrected_rank", "spatial_test_status", "mode_junction",
        "candidate_tier", "selection_rank", "selection_reason",
        "inside_demo_bbox", "region_validation_status", "region_exclusion_reason",
        "reverse_geocoded_locality", "reverse_geocoded_sub_locality", "formatted_address",
        "phase2_run_id", "phase3_run_id", "generated_at",
    ]
    for c in out_cols:
        if c not in validated.columns:
            validated[c] = None
    final = validated[out_cols].copy()

    interim = _abs(ctx.root, ctx.config["outputs"]["interim_dir"]) / "phase3_whitefield_candidates.parquet"
    processed = _abs(ctx.root, ctx.config["outputs"]["processed_dir"]) / "phase3_whitefield_candidates.csv"
    exports.write_parquet(final, interim)
    exports.write_csv(final, processed)
    ctx.outputs["candidates_parquet"] = str(interim)
    ctx.outputs["candidates_csv"] = str(processed)

    primary = final[final["candidate_tier"] == "PRIMARY"]
    reserve = final[final["candidate_tier"] == "RESERVE"]
    report = {
        **counts,
        "primary_candidates": int(len(primary)),
        "reserve_candidates": int(len(reserve)),
        "primary_h3": list(primary["h3_res10"]),
        "reserve_h3": list(reserve["h3_res10"]),
        "primary_reserve_overlap": list(set(primary["h3_res10"]) & set(reserve["h3_res10"])),
        "deterministic": True,
    }
    ctx.report("whitefield_candidate_selection_report.json", report)
    ctx.report(
        "whitefield_region_validation_report.json",
        {
            "bbox": ctx.config["region"]["approximate_demo_bbox"],
            "explicitly_excluded_h3": ctx.config["region"]["explicitly_excluded_h3"],
            "note": "mode_police_station is the dominant ticket station, NOT an official jurisdiction polygon.",
            "status_counts": final["region_validation_status"].value_counts().to_dict(),
        },
    )
    return final


# --------------------------------------------------------------------------- #
# Stage 3 — capability probe                                                   #
# --------------------------------------------------------------------------- #
def _run_capability(ctx: RunContext, client: MapplsClient) -> dict[str, Any]:
    report = cap.run_probe(client)
    ctx.report("mappls_capability_report.json", report)
    ctx.report("authentication_report.json", client.credentials.status_report())
    _write_mappls_request_reports(ctx, client)
    if not report["native_traffic_tiles_available"]:
        ctx.warn("NATIVE_TRAFFIC_TILES_UNAVAILABLE")
    if not report["predictive_traffic_available"]:
        ctx.warn("PREDICTIVE_TRAFFIC_UNAVAILABLE")
    return report


def _write_mappls_request_reports(ctx: RunContext, client: MapplsClient) -> None:
    ctx.report("mappls_request_audit.json", client.call_history)
    ctx.report("mappls_request_summary.json", client.request_summary())


# --------------------------------------------------------------------------- #
# Stage 4 — prepare segments                                                   #
# --------------------------------------------------------------------------- #
def _run_prepare_segments(
    ctx: RunContext,
    candidates: pd.DataFrame,
    client: MapplsClient,
    budget: ApiBudget,
    lin: lineage_mod.Phase2Lineage,
    *,
    limit: int,
) -> pd.DataFrame:
    from .route_adv_adapter import call_route_adv
    from .snap_to_road_adapter import call_snap_to_road
    from .reverse_geocode_adapter import call_reverse_geocode

    primaries = candidates[candidates["candidate_tier"] == "PRIMARY"].head(limit).copy()
    reserves = candidates[candidates["candidate_tier"] == "RESERVE"].copy()
    seg_cfg = ctx.config["segments"]

    directed_rows: list[dict[str, Any]] = []
    gen_records: list[dict[str, Any]] = []
    unresolved: list[str] = []
    reserve_promotions = 0
    geometry_decodes: list[dict[str, Any]] = []

    def route_fn(al, an, bl_, bn):
        return call_route_adv(client, al, an, bl_, bn, budget_scope="prepare")

    snap_fn = (lambda pts: call_snap_to_road(client, pts, budget_scope="prepare")) if seg_cfg.get("snap_to_road", {}).get("enabled") else None
    rg_fn = (lambda lat, lng: call_reverse_geocode(client, lat, lng, budget_scope="prepare")) if seg_cfg.get("reverse_geocode", {}).get("enabled") else None

    meta_by_h3 = candidates.set_index("h3_res10")

    def build(h3: str, lat: float, lng: float) -> bool:
        nonlocal reserve_promotions
        try:
            rec = build_segment_for_h3(
                h3, lat, lng, ctx.config,
                route_adv_fn=route_fn, snap_fn=snap_fn, reverse_geocode_fn=rg_fn,
            )
        except BudgetExceeded:
            raise
        gen_records.append({"h3_res10": h3, "resolved": rec["resolved"], "attempts": len(rec.get("attempts", []))})
        if rec.get("best") and rec["best"].get("geometry_geojson") is not None:
            geometry_decodes.append({
                "h3_res10": h3,
                "decoded_length_m": rec["best"].get("decoded_length_m"),
                "provider_distance_m": rec["best"].get("route_distance_m"),
                "status": "DECODED",
            })
        if not rec["resolved"]:
            return False
        m = meta_by_h3.loc[h3]
        for d in rec["directed"]:
            d["historical_station"] = "WHITEFIELD"
            d["normalized_propensity"] = float(m["normalized_propensity"])
            d["corrected_rank"] = float(m["corrected_rank"])
            d["phase2_run_id"] = lin.phase2_run_id
            d["phase3_run_id"] = ctx.run_id
            directed_rows.append(d)
        return True

    try:
        for _, r in primaries.iterrows():
            ok = build(str(r["h3_res10"]), float(r["centroid_latitude"]), float(r["centroid_longitude"]))
            if not ok:
                unresolved.append(str(r["h3_res10"]))
        # promote reserves for unresolved primaries
        reserve_iter = iter(reserves.itertuples(index=False))
        still_unresolved = []
        for h3 in unresolved:
            promoted = False
            for rr in reserve_iter:
                if build(str(rr.h3_res10), float(rr.centroid_latitude), float(rr.centroid_longitude)):
                    reserve_promotions += 1
                    promoted = True
                    break
            if not promoted:
                still_unresolved.append(h3)
        unresolved = still_unresolved
    except BudgetExceeded as exc:
        ctx.errors.append(f"API_BUDGET_EXCEEDED:{exc.scope}")

    directed = pd.DataFrame(directed_rows)
    if not directed.empty:
        interim = _abs(ctx.root, ctx.config["outputs"]["interim_dir"]) / "phase3_whitefield_road_segments.parquet"
        catalog_csv = _abs(ctx.root, ctx.config["outputs"]["processed_dir"]) / "phase3_whitefield_segment_catalog.csv"
        catalog_geo = _abs(ctx.root, ctx.config["outputs"]["processed_dir"]) / "phase3_whitefield_segment_catalog.geojson"
        # serialize geometry dict to JSON string for parquet/csv friendliness
        directed_out = directed.copy()
        directed_out["route_geometry"] = directed_out["route_geometry"].apply(
            lambda g: __import__("json").dumps(g) if isinstance(g, dict) else g
        )
        exports.write_parquet(directed_out, interim)
        exports.write_csv(directed_out, catalog_csv)
        exports.segments_to_geojson(
            directed,
            ["physical_segment_id", "directed_segment_id", "h3_res10", "direction",
             "road_name", "normalized_propensity", "corrected_rank", "segment_quality_score"],
            catalog_geo,
        )
        ctx.outputs["road_segments_parquet"] = str(interim)
        ctx.outputs["segment_catalog_csv"] = str(catalog_csv)
        ctx.outputs["segment_catalog_geojson"] = str(catalog_geo)

        # provisional baselines from provider non-traffic reference duration
        base_rows = []
        for _, d in directed.iterrows():
            b = bl.compute_baseline(
                live_eta_samples=[],
                provider_non_traffic_s=float(d["route_duration_reference_s"]),
                cfg=bl.config_from(ctx.config),
            )
            b["directed_segment_id"] = d["directed_segment_id"]
            b["h3_res10"] = d["h3_res10"]
            b["baseline_window_start"] = None
            b["baseline_window_end"] = None
            b["last_updated_at"] = now_ist().isoformat()
            base_rows.append(b)
        base_df = pd.DataFrame(base_rows)
        base_path = _abs(ctx.root, ctx.config["outputs"]["live_dir"]) / "phase3_whitefield_segment_baselines.parquet"
        exports.write_parquet(base_df, base_path)
        ctx.outputs["segment_baselines_parquet"] = str(base_path)

    n_physical = directed["physical_segment_id"].nunique() if not directed.empty else 0
    n_directed = len(directed)
    if unresolved:
        ctx.warn("PARTIAL_SEGMENT_COVERAGE")
    ctx.warn("PROVISIONAL_BASELINES_USED")
    ctx.warn("BASELINE_COLD_START")

    seg_report = {
        "primary_h3_requested": int(len(primaries)),
        "valid_physical_segments": int(n_physical),
        "valid_directed_segments": int(n_directed),
        "unresolved_primary_h3": unresolved,
        "unresolved_primary_count": len(unresolved),
        "reserve_promotions": reserve_promotions,
        "segment_coverage_percentage": round(100.0 * n_physical / max(1, len(primaries)), 2),
        "directed_equals_two_times_physical": (n_directed == 2 * n_physical),
    }
    ctx.report("segment_generation_report.json", seg_report)
    ctx.report("segment_validation_report.json", {"records": gen_records})
    ctx.report("route_geometry_decoding_report.json", {"precision": 5, "decodes": geometry_decodes})
    _write_mappls_request_reports(ctx, client)
    return directed


# --------------------------------------------------------------------------- #
# Stage 5 — poll cycle                                                         #
# --------------------------------------------------------------------------- #
def _load_segments(ctx: RunContext) -> pd.DataFrame:
    p = _abs(ctx.root, ctx.config["outputs"]["interim_dir"]) / "phase3_whitefield_road_segments.parquet"
    if not p.exists():
        return pd.DataFrame()
    return pd.read_parquet(p)


def _load_baselines(ctx: RunContext) -> dict[str, dict[str, Any]]:
    p = _abs(ctx.root, ctx.config["outputs"]["live_dir"]) / "phase3_whitefield_segment_baselines.parquet"
    if not p.exists():
        return {}
    df = pd.read_parquet(p)
    return {r["directed_segment_id"]: dict(r) for _, r in df.iterrows()}


def _run_poll(
    ctx: RunContext,
    candidates: pd.DataFrame,
    client: MapplsClient,
    *,
    limit: int,
    directed_override: Optional[pd.DataFrame] = None,
) -> dict[str, Any]:
    from . import polling
    from .observation_store import ObservationStore

    directed = directed_override if directed_override is not None else _load_segments(ctx)
    if directed.empty:
        ctx.errors.append("ALL_PRIMARY_SEGMENTS_UNRESOLVED")
        return {}
    # limit to first `limit` physical segments
    phys_order = list(dict.fromkeys(directed["physical_segment_id"]))[:limit]
    directed = directed[directed["physical_segment_id"].isin(phys_order)].copy()

    baseline_map = _load_baselines(ctx)
    poll_cycle_id = f"{ctx.run_id}_cycle_{now_ist().strftime('%H%M%S')}"
    store = ObservationStore(_abs(ctx.root, ctx.config["storage"]["observations_root"]))
    previous_by_directed = store.latest_valid_by_directed(data_mode=ctx.data_mode)

    result = polling.run_poll_cycle(
        directed_segments=directed,
        candidate_meta=candidates,
        baseline_map=baseline_map,
        client=client,
        config=ctx.config,
        poll_cycle_id=poll_cycle_id,
        data_mode=ctx.data_mode,
        previous_observations_by_directed=previous_by_directed,
    )

    # store observations (live only updates production baselines later)
    store_result = store.write(result["observations"])
    ctx.outputs["observations_root"] = str(store.root)

    obs_df = pd.DataFrame(result["observations"])
    valid = int(obs_df["is_valid_observation"].sum()) if not obs_df.empty else 0
    invalid = int((~obs_df["is_valid_observation"]).sum()) if not obs_df.empty else 0
    if invalid > 0:
        ctx.warn("PARTIAL_LIVE_OBSERVATION_COVERAGE")

    # latest valid observations snapshot
    if not obs_df.empty:
        latest = obs_df[obs_df["is_valid_observation"] == True].copy()  # noqa: E712
        lp = _abs(ctx.root, ctx.config["outputs"]["live_dir"]) / "phase3_whitefield_latest_valid_observations.parquet"
        exports.write_parquet(latest if not latest.empty else obs_df.iloc[0:0], lp)
        ctx.outputs["latest_valid_observations"] = str(lp)

    pic_df = result["pic"]
    if isinstance(pic_df, pd.DataFrame) and not pic_df.empty:
        pic_df = reporting.compute_localized_anomalies(pic_df, ctx.config)
        # confidence columns
        meta = candidates.set_index("h3_res10")
        def _conf(r):
            h3 = r["h3_res10"]
            dd = float(meta.loc[h3, "device_days"]) if h3 in meta.index else None
            sts = meta.loc[h3, "spatial_test_status"] if h3 in meta.index else None
            return conf.compute_all(
                device_days=dd, spatial_test_status=sts,
                baseline_status=r.get("baseline_status"), baseline_sample_count=0,
                live_valid=bool(r.get("live_observation_valid")), fresh=True,
                route_consistent=True,
                directional_coverage_status=r.get("directional_coverage_status"),
            )
        conf_df = pic_df.apply(lambda r: pd.Series(_conf(r)), axis=1)
        for c in conf_df.columns:
            pic_df[c] = conf_df[c]

        _write_congestion_pic_outputs(ctx, result, pic_df)
        if (pic_df.get("directional_coverage_status") == "ONE_DIRECTION_VALID").any():
            ctx.warn("ONE_DIRECTION_ONLY")
        if (pic_df.get("localized_anomaly_status") == "INSUFFICIENT_VALID_NEIGHBORS").any():
            ctx.warn("LOCALIZED_ANOMALY_INSUFFICIENT_NEIGHBORS")
    else:
        pic_df = pd.DataFrame()

    _write_poll_reports(ctx, result, obs_df, store_result, pic_df, client)
    result["pic"] = pic_df
    return result


def _write_congestion_pic_outputs(ctx: RunContext, result: dict[str, Any], pic_df: pd.DataFrame) -> None:
    proc = _abs(ctx.root, ctx.config["outputs"]["processed_dir"])
    cong_df = pd.DataFrame(result["congestion"])
    exports.write_parquet(cong_df, proc / "phase3_whitefield_live_congestion.parquet")
    exports.write_csv(cong_df, proc / "phase3_whitefield_live_congestion.csv")
    ctx.outputs["live_congestion_parquet"] = str(proc / "phase3_whitefield_live_congestion.parquet")
    ctx.outputs["live_congestion_csv"] = str(proc / "phase3_whitefield_live_congestion.csv")

    # join centroids for geojson
    exports.write_parquet(pic_df, proc / "phase3_whitefield_live_pic.parquet")
    exports.write_csv(pic_df, proc / "phase3_whitefield_live_pic.csv")
    exports.write_json_records(
        pic_df, proc / "phase3_whitefield_live_pic.json",
        extra={
            "run_id": ctx.run_id,
            "data_mode": ctx.data_mode,
            "poll_cycle_id": result["poll_cycle_id"],
            "observed_at_ist": result["observed_at_ist"],
            "coverage": "LIVE_TRAFFIC_COVERAGE: WHITEFIELD DEMO REGION",
        },
    )
    cand_path = _abs(ctx.root, ctx.config["outputs"]["interim_dir"]) / "phase3_whitefield_candidates.parquet"
    if cand_path.exists():
        cand = pd.read_parquet(cand_path)[["h3_res10", "centroid_latitude", "centroid_longitude"]]
        geo_df = pic_df.merge(cand, on="h3_res10", how="left")
        exports.points_to_geojson(
            geo_df, "centroid_latitude", "centroid_longitude",
            ["h3_res10", "pic_score", "pic_rank", "congestion_severity", "congestion_label",
             "traffic_label", "current_speed_kmh", "reference_speed_kmh",
             "speed_reduction_percentage", "delay_seconds", "delay_percentage",
             "travel_time_index", "congestion_severity_percentage",
             "eta_change_percentage", "speed_change_percentage",
             "normalized_propensity", "pic_status", "localized_anomaly", "overall_pic_confidence"],
            proc / "phase3_whitefield_live_pic.geojson",
        )
        ctx.outputs["live_pic_geojson"] = str(proc / "phase3_whitefield_live_pic.geojson")
    ctx.outputs["live_pic_parquet"] = str(proc / "phase3_whitefield_live_pic.parquet")
    ctx.outputs["live_pic_csv"] = str(proc / "phase3_whitefield_live_pic.csv")
    ctx.outputs["live_pic_json"] = str(proc / "phase3_whitefield_live_pic.json")


def _write_poll_reports(ctx, result, obs_df, store_result, pic_df, client) -> None:
    c = result["counters"]
    valid = int(obs_df["is_valid_observation"].sum()) if not obs_df.empty else 0
    invalid = int((~obs_df["is_valid_observation"]).sum()) if not obs_df.empty else 0
    requested = int(c["monitored_pairs_requested"])
    ctx.report("polling_report.json", {
        "poll_cycle_id": result["poll_cycle_id"],
        "observed_at_ist": result["observed_at_ist"],
        "data_mode": result["data_mode"],
        "requested_directed_segments": requested,
        "valid_observations": valid,
        "invalid_observations": invalid,
        "observation_coverage_percentage": round(100.0 * valid / max(1, requested), 2),
        "store_result": store_result,
        **c,
    })
    ctx.report("observation_quality_report.json", {
        "quality_status_counts": obs_df["quality_status"].value_counts().to_dict() if not obs_df.empty else {},
        "valid": valid, "invalid": invalid,
    })
    if isinstance(pic_df, pd.DataFrame) and not pic_df.empty:
        ctx.report("baseline_report.json", {
            "baseline_status_counts": pic_df["baseline_status"].value_counts().to_dict(),
        })
        ctx.report("congestion_report.json", reporting.congestion_summary(pic_df))
        ctx.report("pic_report.json", {**reporting.pic_summary(pic_df), "top5": reporting.top_n_pic(pic_df, 5)})
        ctx.report("localized_anomaly_report.json", {
            "cells_computed": int((pic_df.get("localized_anomaly_status") == "COMPUTED").sum()),
            "positive_signal_cells": int((pic_df.get("localized_anomaly_positive") == True).sum()),  # noqa: E712
            "status_counts": pic_df["localized_anomaly_status"].value_counts().to_dict(),
        })
    ctx.report("confidence_methodology.json", conf.methodology())
    if client.budget is not None:
        ctx.report("api_budget_report.json", client.budget.report())
        ctx.report("api_usage_report.json", client.budget.report())
    _write_mappls_request_reports(ctx, client)


# --------------------------------------------------------------------------- #
# Final report + entrypoint                                                    #
# --------------------------------------------------------------------------- #
def _status(ctx: RunContext) -> str:
    if ctx.errors:
        # budget / unresolved errors are BLOCKED, lineage/contract are FAIL
        blocked_markers = ("API_BUDGET_EXCEEDED", "ALL_PRIMARY_SEGMENTS_UNRESOLVED",
                           "MAPPLS_REST_KEY_MISSING", "NO_NUMERIC_ETA_SOURCE_AVAILABLE",
                           "MAPPLS_AUTHENTICATION_DENIED")
        if any(any(m in e for m in blocked_markers) for e in ctx.errors):
            return "BLOCKED"
        return "FAIL"
    if ctx.data_mode == REPLAY:
        return "REPLAY_PASS"
    return "WARN" if ctx.warnings else "PASS"


def _write_final(ctx: RunContext, mode: str, started: float, blocks: dict[str, Any]) -> dict[str, Any]:
    final = {
        "run_id": ctx.run_id,
        "mode": mode,
        "data_mode": ctx.data_mode,
        "status": _status(ctx),
        "duration_seconds": round(time.time() - started, 2),
        **blocks,
        "outputs": ctx.outputs,
        "warnings": ctx.warnings,
        "errors": ctx.errors,
        "honesty": {
            "citywide_historical_coverage": "BENGALURU",
            "live_traffic_coverage": "WHITEFIELD DEMO REGION",
            "claims_direct_parked_car_detection": False,
            "claims_parking_causation": False,
        },
    }
    ctx.report("phase3_final_report.json", final)
    # write manifest
    write_json(ctx.artifact_dir / "manifest.json", {
        "run_id": ctx.run_id,
        "phase": "phase3",
        "mode": mode,
        "data_mode": ctx.data_mode,
        "status": final["status"],
        "config_path": ctx.config.get("_config_path"),
        "completed_at": now_ist().isoformat(),
        "warnings": ctx.warnings,
        "errors": ctx.errors,
    })
    return final


def _citywide_manifest(ctx: RunContext, lin: lineage_mod.Phase2Lineage) -> None:
    proc = _abs(ctx.root, ctx.config["outputs"]["processed_dir"])
    payload = {
        "live_traffic_coverage": "WHITEFIELD_DEMO_ONLY",
        "citywide_historical_coverage": "BENGALURU",
        "phase2_run_id": lin.phase2_run_id,
        "phase2_status": lin.phase2_status,
        "citywide_historical_h3_cells": lin.loaded_h3_rows,
        "phase2_h3_hotspots_parquet": str(lin.input_dataset_path),
        "phase2_h3_hotspots_geojson": str(lin.artifact_dir.parent.parent / "data/processed/phase2_h3_hotspots.geojson"),
        "note": "Phase 3 does not duplicate Phase 2 modelling; this is a pointer to the verified citywide layer.",
    }
    p = proc / "phase3_citywide_historical_layer_manifest.json"
    write_json(p, payload)
    ctx.outputs["citywide_historical_layer_manifest"] = str(p)


def run_phase3(
    mode: str,
    config_path: str = "configs/phase3.yaml",
    *,
    limit: int = 20,
    cycles: int = 1,
    interval_minutes: int = 15,
    fixture_dir: Optional[str] = None,
    root: str | Path | None = None,
) -> dict[str, Any]:
    started = time.time()
    root_path = repo_root(root)
    config = load_config(config_path, root_path)

    data_mode = REPLAY if mode == "replay" else LIVE
    ctx = _new_context(config, root_path, mode, data_mode)

    creds = load_credentials(config)
    budget = ApiBudget.from_config(config)
    replay_dir = fixture_dir or config["replay"]["fixture_root"]
    client = MapplsClient(
        config, creds, data_mode=data_mode,
        replay_dir=(_abs(root_path, replay_dir) if data_mode == REPLAY else None),
        budget=budget,
    )

    blocks: dict[str, Any] = {}
    lin: Optional[lineage_mod.Phase2Lineage] = None
    try:
        lin = _run_lineage(ctx)
        _citywide_manifest(ctx, lin)
        blocks["phase2_lineage"] = {
            "phase2_run_id": lin.phase2_run_id,
            "phase2_status": lin.phase2_status,
            "checksum_match": lin.checksum_match,
            "loaded_h3_cells": lin.loaded_h3_rows,
            "phase1_run_id": lin.phase1_run_id,
        }
        blocks["coverage"] = reporting.coverage_block(lin.loaded_h3_rows)

        if mode == "lineage-only":
            return _write_final(ctx, mode, started, blocks)

        candidates = _run_candidates(
            ctx, lin, client=client if data_mode == LIVE else None,
            reverse_geocode=(mode in ("prepare-segments",) and data_mode == LIVE),
        )
        counts = cs.selection_counts(lin.hotspots, config)
        blocks["candidate_selection"] = {
            **{k: counts[k] for k in ("whitefield_h3_cells", "eligible_whitefield_h3_cells", "tested_whitefield_h3_cells")},
            "explicitly_excluded_h3_cells": counts["explicitly_excluded_h3_cells"],
            "primary_candidates": int((candidates["candidate_tier"] == "PRIMARY").sum()),
            "reserve_candidates": int((candidates["candidate_tier"] == "RESERVE").sum()),
        }

        if mode == "select-candidates":
            return _write_final(ctx, mode, started, blocks)

        if mode == "capability-probe":
            blocks["mappls"] = _run_capability(ctx, client)
            blocks["mappls_request_summary"] = client.request_summary()
            return _write_final(ctx, mode, started, blocks)

        if mode == "replay":
            # self-contained replay: build a synthetic directed segment table from fixtures
            directed = _replay_segments(ctx, client, candidates)
            if not directed.empty:
                catalog_geo = _abs(ctx.root, config["outputs"]["processed_dir"]) / "phase3_whitefield_segment_catalog.geojson"
                exports.segments_to_geojson(
                    directed,
                    ["physical_segment_id", "directed_segment_id", "h3_res10", "direction", "road_name"],
                    catalog_geo,
                )
                ctx.outputs["segment_catalog_geojson"] = str(catalog_geo)
            result = _run_poll(ctx, candidates, client, limit=limit, directed_override=directed)
            blocks["poll_cycle"] = _poll_block(result)
            blocks["mappls_request_summary"] = client.request_summary()
            return _write_final(ctx, mode, started, blocks)

        # LIVE segment/poll modes require capability + key
        if not creds.has_rest_key:
            ctx.errors.append("MAPPLS_REST_KEY_MISSING")
            return _write_final(ctx, mode, started, blocks)
        cap_report = _run_capability(ctx, client)
        blocks["mappls"] = {
            "authentication_status": "STATIC_REST_KEY" if creds.has_rest_key else "MISSING",
            "selected_reference_source": cap_report["selected_reference_source"],
            "selected_live_source": cap_report["selected_live_source"],
            "matrix_eta_available": cap_report["endpoint_status"].get("DISTANCE_MATRIX_ETA") == "AVAILABLE",
            "route_eta_available": cap_report["endpoint_status"].get("ROUTE_ETA") == "AVAILABLE",
            "native_traffic_tiles_available": False,
            "predictive_traffic_available": False,
        }
        if not cap_report["numeric_live_traffic_available"] and mode in ("poll-once", "collect"):
            ctx.errors.append("NO_NUMERIC_ETA_SOURCE_AVAILABLE")
            return _write_final(ctx, mode, started, blocks)

        if mode == "prepare-segments":
            directed = _run_prepare_segments(ctx, candidates, client, budget, lin, limit=limit)
            blocks["segments"] = _segment_block(ctx, directed, limit)
            blocks["mappls_request_summary"] = client.request_summary()
            return _write_final(ctx, mode, started, blocks)

        if mode in ("poll-once", "collect"):
            n = 1 if mode == "poll-once" else max(1, cycles)
            last_result = {}
            for i in range(n):
                budget.reset_cycle()
                last_result = _run_poll(ctx, candidates, client, limit=limit)
                if ctx.errors:
                    break
                if mode == "collect" and i < n - 1:
                    time.sleep(max(1, interval_minutes) * 60)
            blocks["poll_cycle"] = _poll_block(last_result)
            blocks["api_usage"] = budget.report()
            blocks["mappls_request_summary"] = client.request_summary()
            return _write_final(ctx, mode, started, blocks)

        ctx.errors.append(f"UNKNOWN_MODE:{mode}")
        return _write_final(ctx, mode, started, blocks)

    except lineage_mod.LineageError as exc:
        ctx.errors.append(f"{exc.code}: {'; '.join(exc.errors)}")
        return _write_final(ctx, mode, started, blocks)
    except Exception as exc:  # last-resort: record, never leak secrets
        ctx.errors.append(redact(f"{type(exc).__name__}: {exc}"))
        return _write_final(ctx, mode, started, blocks)


def _segment_block(ctx: RunContext, directed: pd.DataFrame, limit: int) -> dict[str, Any]:
    n_phys = directed["physical_segment_id"].nunique() if not directed.empty else 0
    return {
        "primary_h3_requested": limit,
        "valid_physical_segments": int(n_phys),
        "valid_directed_segments": int(len(directed)),
        "unresolved_primary_h3": max(0, limit - n_phys),
        "segment_coverage_percentage": round(100.0 * n_phys / max(1, limit), 2),
    }


def _poll_block(result: dict[str, Any]) -> dict[str, Any]:
    if not result:
        return {"poll_cycle_id": "", "valid_observations": 0, "invalid_observations": 0}
    obs = pd.DataFrame(result.get("observations", []))
    valid = int(obs["is_valid_observation"].sum()) if not obs.empty else 0
    invalid = int((~obs["is_valid_observation"]).sum()) if not obs.empty else 0
    req = int(result["counters"]["monitored_pairs_requested"])
    return {
        "poll_cycle_id": result.get("poll_cycle_id", ""),
        "observed_at_ist": result.get("observed_at_ist", ""),
        "requested_directed_segments": req,
        "valid_observations": valid,
        "invalid_observations": invalid,
        "observation_coverage_percentage": round(100.0 * valid / max(1, req), 2),
        "matrix_cells_returned": int(result["counters"]["matrix_cells_returned"]),
        "monitored_pairs_used": int(result["counters"]["monitored_pairs_extracted"]),
    }


def _replay_segments(ctx: RunContext, client: MapplsClient, candidates: pd.DataFrame) -> pd.DataFrame:
    """Synthesize a directed-segment table around primary centroids for replay.

    Replay uses fixed fixtures whose geometry need not match each Whitefield H3, so
    segments are constructed deterministically from each centroid (the geometry
    decoder is exercised separately in tests). Reference durations come from the
    Route ADV replay fixture. All rows are REPLAY by construction.
    """
    from . import geometry_utils as geo
    from . import segment_validation as sv
    from .route_adv_adapter import call_route_adv

    seg_cfg = ctx.config["segments"]
    algo = seg_cfg.get("segment_algorithm_version", "phase3-seg-v1")
    target = float(seg_cfg["target_length_m"])
    # one Route ADV replay call to obtain a reference duration/distance
    try:
        route, _ = call_route_adv(client, 12.97, 77.59, 12.975, 77.599, budget_scope="prepare")
        ref_dur = route.duration_s
        ref_dist = route.distance_m
        road_name = route.road_name or "Whitefield demo road"
    except Exception:
        ref_dur, ref_dist, road_name = 188.9, 1626.2, "Whitefield demo road"

    primaries = candidates[candidates["candidate_tier"] == "PRIMARY"].head(2)
    rows = []
    created = now_ist().isoformat()
    for _, r in primaries.iterrows():
        h3 = str(r["h3_res10"])
        lat, lng = float(r["centroid_latitude"]), float(r["centroid_longitude"])
        a = geo.destination_point(lat, lng, 45.0, target / 2.0)
        b = geo.destination_point(lat, lng, 225.0, target / 2.0)
        phys = sv.physical_segment_id(h3, a, b, algo)
        geom = geo.to_geojson_linestring([a, b])
        for direction, (sa, sb) in (("A_TO_B", (a, b)), ("B_TO_A", (b, a))):
            rows.append({
                "physical_segment_id": phys,
                "directed_segment_id": sv.directed_segment_id(phys, direction),
                "h3_res10": h3,
                "direction": direction,
                "endpoint_a_latitude": sa[0], "endpoint_a_longitude": sa[1],
                "endpoint_b_latitude": sb[0], "endpoint_b_longitude": sb[1],
                "route_distance_m": ref_dist,
                "route_duration_reference_s": ref_dur,
                "reference_duration_source": "route_adv",
                "route_geometry": geom,
                "route_midpoint_latitude": lat, "route_midpoint_longitude": lng,
                "midpoint_distance_from_h3_m": 0.0,
                "route_intersects_or_near_h3": True,
                "route_detour_ratio": 1.0,
                "snap_used": False, "snap_status": "NOT_USED",
                "route_status": "OK", "segment_status": "VALID",
                "segment_quality_score": 1.0, "segment_algorithm_version": algo,
                "road_name": road_name, "locality": None, "sub_locality": None,
                "formatted_address": None, "segment_created_at": created,
                "historical_station": "WHITEFIELD",
                "normalized_propensity": float(r["normalized_propensity"]),
                "corrected_rank": float(r["corrected_rank"]),
                "phase2_run_id": "", "phase3_run_id": ctx.run_id,
            })
    return pd.DataFrame(rows)
