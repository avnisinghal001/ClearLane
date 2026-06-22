"""One live poll cycle: Matrix ETA -> observations -> congestion -> PIC.

Physical segments are grouped into batches; each batch is ONE Matrix ETA request.
Within a batch the point list is [A0,B0,A1,B1,...]; only the explicit within-segment
cells (2i->2i+1 = A_TO_B, 2i+1->2i = B_TO_A) are interpreted as monitored pairs.
Cross-segment cells are counted as unused, never mistaken for a monitored segment.
"""

from __future__ import annotations

import math
from typing import Any, Optional

import pandas as pd

from . import baselines as bl
from . import confidence as conf
from . import congestion as cong
from . import pic as pic_mod
from .common import now_ist, now_utc, observation_bucket, to_ist
from .matrix_eta_adapter import call_matrix_eta, extract_pair
from .observation_store import observation_id
from .response_parsers import ProviderError

VALID = "VALID"
ROUTE_REFERENCE_MISMATCH = "ROUTE_REFERENCE_MISMATCH"


def _batch(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _quality_check(
    *,
    eta_distance_m: Optional[float],
    eta_duration_s: Optional[float],
    reference_distance_m: Optional[float],
    quality: dict[str, Any],
) -> tuple[bool, str, list[str], Optional[float]]:
    flags: list[str] = []
    if eta_distance_m is None:
        return False, "MISSING_DISTANCE", ["MISSING_DISTANCE"], None
    if eta_duration_s is None:
        return False, "MISSING_DURATION", ["MISSING_DURATION"], None
    if not math.isfinite(eta_distance_m) or eta_distance_m <= 0:
        return False, "INVALID_DISTANCE", ["INVALID_DISTANCE"], None
    if not math.isfinite(eta_duration_s) or eta_duration_s <= 0:
        return False, "INVALID_DURATION", ["INVALID_DURATION"], None
    if not (quality["minimum_distance_m"] <= eta_distance_m <= quality["maximum_distance_m"]):
        flags.append("DISTANCE_OUT_OF_RANGE")
    if not (quality["minimum_duration_seconds"] <= eta_duration_s <= quality["maximum_duration_seconds"]):
        flags.append("DURATION_OUT_OF_RANGE")

    diff_ratio = None
    if reference_distance_m and reference_distance_m > 0:
        diff_ratio = abs(eta_distance_m - reference_distance_m) / reference_distance_m
        if diff_ratio > quality["maximum_distance_change_ratio"]:
            return False, ROUTE_REFERENCE_MISMATCH, ["ROUTE_REFERENCE_MISMATCH"], diff_ratio

    if flags:
        return True, "VALID_WITH_WARNING", flags, diff_ratio
    return True, VALID, [], diff_ratio


def _matrix_pair(
    matrix,
    *,
    source_index: int,
    dest_index: int,
    source_position: int,
    dest_position: int,
    point_count: int,
    source_count: int,
    destination_count: int,
) -> tuple[float | None, float | None]:
    """Extract one monitored pair from either a subset or full Mappls matrix.

    Live calls now send explicit `sources` and `destinations`, so Mappls returns
    rows/columns in request-list position order. Replay fixtures are full square
    matrices, so they are indexed by the original point indices.
    """
    if matrix.rows == source_count and matrix.cols == destination_count:
        return extract_pair(matrix, source_position, dest_position)
    if matrix.rows == point_count and matrix.cols == point_count:
        return extract_pair(matrix, source_index, dest_index)
    dist, dur = extract_pair(matrix, source_position, dest_position)
    if dist is not None or dur is not None:
        return dist, dur
    return extract_pair(matrix, source_index, dest_index)


def run_poll_cycle(
    *,
    directed_segments: pd.DataFrame,
    candidate_meta: pd.DataFrame,
    baseline_map: dict[str, dict[str, Any]],
    client,
    config: dict[str, Any],
    poll_cycle_id: str,
    data_mode: str = "LIVE",
) -> dict[str, Any]:
    """Returns a dict with observations, per-segment + per-H3 congestion, PIC, and counters."""
    quality = config["quality"]
    bucket_minutes = int(config["polling"]["observation_bucket_minutes"])
    batch_size = int(config["mappls"]["request"]["matrix_physical_segments_per_batch"])
    provider = "mappls"

    observed_at = now_utc()
    observed_ist = to_ist(observed_at)
    bucket = observation_bucket(observed_at, bucket_minutes)

    # group directed rows by physical segment, expecting A_TO_B + B_TO_A
    phys_groups: dict[str, dict[str, pd.Series]] = {}
    order: list[str] = []
    for _, r in directed_segments.iterrows():
        pid = r["physical_segment_id"]
        if pid not in phys_groups:
            phys_groups[pid] = {}
            order.append(pid)
        phys_groups[pid][r["direction"]] = r

    counters = {
        "matrix_rows": 0,
        "matrix_columns": 0,
        "matrix_cells_returned": 0,
        "monitored_pairs_requested": 0,
        "monitored_pairs_extracted": 0,
        "unused_matrix_cells": 0,
        "requests_attempted": 0,
        "requests_failed": 0,
    }
    observations: list[dict[str, Any]] = []

    for batch in _batch(order, batch_size):
        # build points [A0,B0,A1,B1,...]
        points: list[tuple[float, float]] = []
        pid_index: dict[str, tuple[int, int]] = {}
        ordered_pids: list[str] = []
        for pid in batch:
            grp = phys_groups[pid]
            ref = grp["A_TO_B"] if "A_TO_B" in grp else next(iter(grp.values()))
            a = (float(ref["endpoint_a_latitude"]), float(ref["endpoint_a_longitude"]))
            b = (float(ref["endpoint_b_latitude"]), float(ref["endpoint_b_longitude"]))
            ia = len(points)
            points.append(a)
            ib = len(points)
            points.append(b)
            pid_index[pid] = (ia, ib)
            ordered_pids.append(pid)
            counters["monitored_pairs_requested"] += 2

        forward_sources = [pid_index[pid][0] for pid in ordered_pids]
        forward_destinations = [pid_index[pid][1] for pid in ordered_pids]
        reverse_sources = [pid_index[pid][1] for pid in ordered_pids]
        reverse_destinations = [pid_index[pid][0] for pid in ordered_pids]

        matrices: dict[str, Any] = {}
        raws: dict[str, Any] = {}
        provider_statuses: dict[str, str] = {}
        request_specs = {
            "A_TO_B": (forward_sources, forward_destinations),
            "B_TO_A": (reverse_sources, reverse_destinations),
        }
        for direction, (sources, destinations) in request_specs.items():
            counters["requests_attempted"] += 1
            try:
                matrix, raw = call_matrix_eta(
                    client,
                    points,
                    sources=sources,
                    destinations=destinations,
                    budget_scope="poll",
                )
                matrices[direction] = matrix
                raws[direction] = raw
                counters["matrix_rows"] += matrix.rows
                counters["matrix_columns"] += matrix.cols
                counters["matrix_cells_returned"] += matrix.rows * matrix.cols
            except ProviderError as exc:
                provider_statuses[direction] = exc.provider_status
                counters["requests_failed"] += 1
            except Exception:
                provider_statuses[direction] = "NETWORK_ERROR"
                counters["requests_failed"] += 1

        position_by_pid = {pid: i for i, pid in enumerate(ordered_pids)}
        for pid in batch:
            grp = phys_groups[pid]
            ia, ib = pid_index[pid]
            for direction, (si, di) in (("A_TO_B", (ia, ib)), ("B_TO_A", (ib, ia))):
                if direction not in grp:
                    continue
                seg = grp[direction]
                ref_dist = float(seg["route_distance_m"])
                eta_dist = eta_dur = None
                matrix = matrices.get(direction)
                raw = raws.get(direction)
                if matrix is not None:
                    pos = position_by_pid[pid]
                    eta_dist, eta_dur = _matrix_pair(
                        matrix,
                        source_index=si,
                        dest_index=di,
                        source_position=pos,
                        dest_position=pos,
                        point_count=len(points),
                        source_count=len(request_specs[direction][0]),
                        destination_count=len(request_specs[direction][1]),
                    )
                    counters["monitored_pairs_extracted"] += 1

                if matrix is None:
                    is_valid, qstatus, qflags, diff_ratio = (
                        False,
                        provider_statuses.get(direction) or "NETWORK_ERROR",
                        [provider_statuses.get(direction) or "NETWORK_ERROR"],
                        None,
                    )
                else:
                    is_valid, qstatus, qflags, diff_ratio = _quality_check(
                        eta_distance_m=eta_dist,
                        eta_duration_s=eta_dur,
                        reference_distance_m=ref_dist,
                        quality=quality,
                    )

                obs = {
                    "phase3_run_id": config.get("_run_id", ""),
                    "poll_cycle_id": poll_cycle_id,
                    "observed_at_utc": observed_at.isoformat(),
                    "observed_at_ist": observed_ist.isoformat(),
                    "observation_bucket_ist": bucket,
                    "data_mode": data_mode,
                    "provider": provider,
                    "api_operation": "distance_matrix_eta",
                    "provider_request_id": getattr(raw, "provider_request_id", None) if matrix is not None else None,
                    "sanitized_response_sha256": getattr(raw, "sanitized_sha256", "") if matrix is not None else "",
                    "physical_segment_id": pid,
                    "directed_segment_id": seg["directed_segment_id"],
                    "h3_res10": seg["h3_res10"],
                    "direction": direction,
                    "source_latitude": float(seg["endpoint_a_latitude"]),
                    "source_longitude": float(seg["endpoint_a_longitude"]),
                    "target_latitude": float(seg["endpoint_b_latitude"]),
                    "target_longitude": float(seg["endpoint_b_longitude"]),
                    "reference_distance_m": ref_dist,
                    "eta_distance_m": eta_dist,
                    "distance_difference_ratio": diff_ratio,
                    "reference_duration_s": float(seg["route_duration_reference_s"]),
                    "live_eta_duration_s": eta_dur,
                    "http_status": getattr(raw, "http_status", None) if matrix is not None else None,
                    "provider_status": qstatus if not is_valid else "OK",
                    "api_latency_ms": getattr(raw, "latency_ms", None) if matrix is not None else None,
                    "attempt_count": getattr(raw, "attempt_count", None) if matrix is not None else None,
                    "is_valid_observation": bool(is_valid),
                    "quality_status": qstatus,
                    "quality_flags": ",".join(qflags),
                    "created_at": now_ist().isoformat(),
                }
                obs["observation_id"] = observation_id(obs)
                observations.append(obs)

    # cross cells unused
    counters["unused_matrix_cells"] = max(
        0, counters["matrix_cells_returned"] - counters["monitored_pairs_extracted"]
    )

    congestion_rows, pic_input = _compute_congestion(
        observations, phys_groups, candidate_meta, baseline_map, config
    )
    ranked = pic_mod.rank_pic(pd.DataFrame(pic_input), poll_cycle_id) if pic_input else pd.DataFrame()

    return {
        "poll_cycle_id": poll_cycle_id,
        "observed_at_utc": observed_at.isoformat(),
        "observed_at_ist": observed_ist.isoformat(),
        "observation_bucket_ist": bucket,
        "data_mode": data_mode,
        "observations": observations,
        "congestion": congestion_rows,
        "pic": ranked,
        "counters": counters,
    }


def _baseline_reference(seg: pd.Series, baseline_map: dict[str, dict[str, Any]]) -> tuple[Optional[float], str]:
    b = baseline_map.get(seg["directed_segment_id"])
    if b and b.get("free_flow_reference_duration_s") is not None and bl.is_usable(b.get("baseline_status", "")):
        return float(b["free_flow_reference_duration_s"]), b["baseline_status"]
    # fall back to provider reference duration as provisional
    return float(seg["route_duration_reference_s"]), bl.PROVISIONAL_MAPPLS


def _compute_congestion(observations, phys_groups, candidate_meta, baseline_map, config):
    meta = candidate_meta.set_index("h3_res10")
    obs_by_directed = {o["directed_segment_id"]: o for o in observations}

    congestion_rows: list[dict[str, Any]] = []
    h3_severity: dict[str, dict[str, Any]] = {}

    for pid, grp in phys_groups.items():
        dir_sev: dict[str, Optional[float]] = {"A_TO_B": None, "B_TO_A": None}
        dir_eta: dict[str, Optional[float]] = {"A_TO_B": None, "B_TO_A": None}
        ref_used = None
        baseline_status = bl.UNAVAILABLE
        h3 = None
        for direction, seg in grp.items():
            h3 = seg["h3_res10"]
            ref_s, baseline_status = _baseline_reference(seg, baseline_map)
            ref_used = ref_s
            o = obs_by_directed.get(seg["directed_segment_id"])
            if o and o["is_valid_observation"]:
                sev = cong.congestion_severity(o["live_eta_duration_s"], ref_s)
                dir_sev[direction] = sev
                dir_eta[direction] = o["live_eta_duration_s"]
        agg = cong.aggregate_directions(dir_sev["A_TO_B"], dir_sev["B_TO_A"])
        row = {
            "physical_segment_id": pid,
            "h3_res10": h3,
            "a_to_b_eta_s": dir_eta["A_TO_B"],
            "b_to_a_eta_s": dir_eta["B_TO_A"],
            "a_to_b_severity": dir_sev["A_TO_B"],
            "b_to_a_severity": dir_sev["B_TO_A"],
            "reference_duration_s": ref_used,
            "baseline_status": baseline_status,
            **agg,
        }
        congestion_rows.append(row)
        if h3 is not None:
            h3_severity[h3] = row

    pic_input = []
    for h3, row in h3_severity.items():
        sev = row["maximum_severity"]
        m = meta.loc[h3] if h3 in meta.index else None
        prop = float(m["normalized_propensity"]) if m is not None else None
        live_valid = sev is not None
        baseline_usable = bl.is_usable(row["baseline_status"])
        c = cong.compute(
            row["a_to_b_eta_s"] if row["a_to_b_severity"] == sev else row["b_to_a_eta_s"],
            row["reference_duration_s"],
        ) if sev is not None else cong.compute(None, None)
        pic_input.append(
            {
                "h3_res10": h3,
                "historical_station": "WHITEFIELD",
                "corrected_rank": float(m["corrected_rank"]) if m is not None else None,
                "normalized_propensity": prop,
                "reference_duration_s": row["reference_duration_s"],
                "live_eta_duration_s": dir_eta_for_max(row),
                "travel_time_index": c["travel_time_index"],
                "delay_seconds": c["delay_seconds"],
                "congestion_severity": sev,
                "congestion_label": cong.severity_label(sev),
                "baseline_status": row["baseline_status"],
                "live_observation_valid": live_valid,
                "baseline_usable": baseline_usable,
                "directional_coverage_status": row["directional_coverage_status"],
            }
        )
    return congestion_rows, pic_input


def dir_eta_for_max(row: dict[str, Any]) -> Optional[float]:
    if row["maximum_severity_direction"] == "A_TO_B":
        return row["a_to_b_eta_s"]
    if row["maximum_severity_direction"] == "B_TO_A":
        return row["b_to_a_eta_s"]
    return None
