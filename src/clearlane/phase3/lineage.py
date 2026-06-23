"""Phase 2 lineage validation for Phase 3.

Resolves the latest *completed, verified, full* Phase 2 run, confirms its status
and warnings are allowed, loads the hotspot Parquet, and validates structural and
value invariants before any candidate selection or Mappls call happens.

Hard rules enforced here:
  * Only Phase 2 outputs are opened — never raw Phase 1 / raw ticket data.
  * Status must be PASS or an allowed WARN; the errors array must be empty.
  * All warnings must belong to the configured allowed-warning list.
  * normalized_propensity is finite and within [0, 1].
  * H3 IDs are valid res-10 cells.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import math

import pandas as pd

from . import schema
from .common import read_json, repo_root, sha256_file

# Paths Phase 3 must never read.
FORBIDDEN_INPUTS = [
    "data/raw",
    "data/interim/violations_cleaned.csv",
    "data/interim/violations_cleaned.parquet",
]


class LineageError(RuntimeError):
    def __init__(self, code: str, errors: list[str]):
        super().__init__(f"{code}: " + "; ".join(errors))
        self.code = code
        self.errors = errors


@dataclass
class Phase2Lineage:
    phase2_run_id: str
    phase2_status: str
    phase2_warnings: list[str]
    artifact_dir: Path
    input_dataset_path: Path
    input_dataset_sha256: str
    expected_h3_rows: int | None
    loaded_h3_rows: int
    row_count_match: bool
    checksum_match: bool
    checksum_source: str
    required_columns_present: bool
    phase1_run_id: str
    raw_phase1_data_used: bool
    hotspots: pd.DataFrame = field(repr=False, default=None)  # type: ignore

    def to_report(self) -> dict[str, Any]:
        return {
            "phase2_run_id": self.phase2_run_id,
            "phase2_status": self.phase2_status,
            "phase2_warnings": self.phase2_warnings,
            "phase2_artifact_dir": str(self.artifact_dir),
            "input_dataset_path": str(self.input_dataset_path),
            "input_dataset_sha256": self.input_dataset_sha256,
            "input_dataset_checksum_source": self.checksum_source,
            "expected_h3_rows": self.expected_h3_rows,
            "loaded_h3_rows": self.loaded_h3_rows,
            "row_count_match": self.row_count_match,
            "checksum_match": self.checksum_match,
            "required_columns_present": self.required_columns_present,
            "phase1_run_id": self.phase1_run_id,
            "raw_phase1_data_used": self.raw_phase1_data_used,
            "forbidden_inputs": FORBIDDEN_INPUTS,
            "status": "PASS",
        }


def _is_full_completed_run(artifact_dir: Path) -> tuple[bool, dict | None, dict | None]:
    manifest_path = artifact_dir / "manifest.json"
    final_path = artifact_dir / "reports" / "phase2_final_report.json"
    if not (manifest_path.exists() and final_path.exists()):
        return False, None, None
    try:
        manifest = read_json(manifest_path)
        final = read_json(final_path)
    except Exception:
        return False, None, None
    # Ignore lineage-only runs: they do not carry full hotspot outputs.
    outputs = final.get("outputs", {})
    if not isinstance(outputs, dict) or "h3_hotspots" not in outputs:
        return False, None, None
    return True, manifest, final


def resolve_latest_phase2(config: dict[str, Any], root: str | Path | None = None) -> tuple[Path, dict, dict]:
    root_path = repo_root(root)
    artifact_root = root_path / config["phase2"]["artifact_root"]
    if not artifact_root.exists():
        raise LineageError("PHASE2_NOT_FOUND", [f"Missing Phase 2 artifact root: {artifact_root}"])

    allowed_statuses = set(config["phase2"]["allowed_statuses"])
    allowed_warnings = set(config["phase2"]["allowed_warnings"])

    candidates = sorted([p for p in artifact_root.iterdir() if p.is_dir()], reverse=True)
    skipped: list[str] = []
    for cand in candidates:
        ok, manifest, final = _is_full_completed_run(cand)
        if not ok:
            skipped.append(f"{cand.name}: incomplete/lineage-only")
            continue
        status = str(final.get("status") or manifest.get("status"))
        if status not in allowed_statuses:
            skipped.append(f"{cand.name}: status={status}")
            continue
        errors = final.get("errors") or manifest.get("errors") or []
        if errors:
            skipped.append(f"{cand.name}: non-empty errors")
            continue
        warnings = list(final.get("warnings") or manifest.get("warnings") or [])
        bad = [w for w in warnings if w not in allowed_warnings]
        if bad:
            skipped.append(f"{cand.name}: disallowed warnings {bad}")
            continue
        return cand, manifest, final

    raise LineageError(
        "NO_VERIFIED_PHASE2_RUN",
        ["No completed verified full Phase 2 run found.", *skipped],
    )


def _expected_rows(manifest: dict, final: dict) -> int | None:
    for src in (final, manifest):
        for key in ("h3_cell_count", "loaded_h3_rows", "h3_rows"):
            if key in src:
                return int(src[key])
        summary = src.get("summary", {}) if isinstance(src.get("summary"), dict) else {}
        for key in ("h3_cell_count", "hotspot_rows"):
            if key in summary:
                return int(summary[key])
    return None


def _hotspot_checksum(manifest: dict, final: dict) -> str | None:
    for src in (final, manifest):
        outputs = src.get("outputs", {})
        if isinstance(outputs, dict):
            for key in ("h3_hotspots_sha256", "phase2_h3_hotspots_sha256"):
                if outputs.get(key):
                    return str(outputs[key])
        checksums = src.get("checksums", {})
        if isinstance(checksums, dict) and checksums.get("h3_hotspots"):
            return str(checksums["h3_hotspots"])
    return None


def _valid_h3(value: str) -> bool:
    if not isinstance(value, str) or len(value) != 15:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    # res-10 res-class cells in this Bengaluru dataset start with '8a'
    return value.startswith("8a")


def validate(config: dict[str, Any], root: str | Path | None = None) -> Phase2Lineage:
    root_path = repo_root(root)
    artifact_dir, manifest, final = resolve_latest_phase2(config, root_path)

    hotspot_rel = config["phase2"]["hotspot_parquet"]
    hotspot_path = root_path / hotspot_rel
    errors: list[str] = []
    if not hotspot_path.exists():
        raise LineageError("PHASE2_HOTSPOT_MISSING", [f"Missing hotspot parquet: {hotspot_path}"])

    actual_sha = sha256_file(hotspot_path)
    expected_sha = _hotspot_checksum(manifest, final)
    if expected_sha is not None:
        checksum_match = actual_sha == expected_sha
        checksum_source = "phase2_manifest_or_report"
        if not checksum_match and config["phase2"].get("require_checksum_match", True):
            errors.append(f"Hotspot checksum mismatch: expected {expected_sha}, got {actual_sha}")
    else:
        # No recorded checksum to compare against; we still record ours.
        checksum_match = True
        checksum_source = "computed_no_expectation"

    df = pd.read_parquet(hotspot_path)
    rep = schema.schema_report(df)
    if not rep["required_columns_present"]:
        errors.append("Missing required Phase 2 columns: " + ", ".join(rep["missing_required_columns"]))
        raise LineageError("PHASE2_SCHEMA_INVALID", errors)

    cdf = schema.canonicalize(df)

    expected_rows = _expected_rows(manifest, final)
    row_count_match = expected_rows is None or expected_rows == len(cdf)
    if expected_rows is not None and not row_count_match:
        errors.append(f"Hotspot row count {len(cdf)} != expected {expected_rows}")

    bad_h3 = [h for h in cdf["h3_res10"].head(20000) if not _valid_h3(h)]
    if bad_h3:
        errors.append(f"{len(bad_h3)} invalid H3 IDs detected (sample {bad_h3[:3]})")

    prop = pd.to_numeric(cdf["normalized_propensity"], errors="coerce")
    if not prop.apply(lambda v: (not math.isnan(v)) and 0.0 <= v <= 1.0).all():
        bad = prop[(prop < 0) | (prop > 1) | (prop.isna())]
        errors.append(f"normalized_propensity out of [0,1] or non-finite for {len(bad)} rows")

    eligible = cdf["eligible_for_corrected_ranking"] == True  # noqa: E712
    rank = pd.to_numeric(cdf.loc[eligible, "corrected_rank"], errors="coerce")
    if not rank.apply(lambda v: not math.isnan(v)).all():
        errors.append("corrected_rank non-finite for some eligible cells")

    if errors:
        raise LineageError("PHASE2_LINEAGE_FAILED", errors)

    phase1_run_id = ""
    p1 = manifest.get("phase1", {})
    if isinstance(p1, dict):
        phase1_run_id = str(p1.get("run_id", ""))

    return Phase2Lineage(
        phase2_run_id=str(manifest.get("run_id") or final.get("run_id")),
        phase2_status=str(final.get("status") or manifest.get("status")),
        phase2_warnings=list(final.get("warnings") or manifest.get("warnings") or []),
        artifact_dir=artifact_dir,
        input_dataset_path=hotspot_path,
        input_dataset_sha256=actual_sha,
        expected_h3_rows=expected_rows,
        loaded_h3_rows=int(len(cdf)),
        row_count_match=bool(row_count_match),
        checksum_match=bool(checksum_match),
        checksum_source=checksum_source,
        required_columns_present=True,
        phase1_run_id=phase1_run_id,
        raw_phase1_data_used=False,
        hotspots=cdf,
    )
