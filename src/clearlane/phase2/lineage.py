from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import yaml

from clearlane.phase1.fingerprint import sha256_file


PHASE2_INPUT_NOT_VERIFIED = "PHASE2_INPUT_NOT_VERIFIED"

REQUIRED_PHASE1_REPORTS = [
    "phase1_final_report.json",
    "row_reconciliation.json",
    "data_dictionary.csv",
    "document_claims_comparison.csv",
]

REQUIRED_CLEANED_COLUMNS = [
    "latitude_numeric",
    "longitude_numeric",
    "created_date",
    "device_id",
    "created_by_id",
    "vehicle_number_normalized",
    "vehicle_type_normalized",
    "violation_labels",
    "primary_violation_label",
    "contains_parking_related_label",
    "police_station_normalized",
    "junction_name_normalized",
    "validation_status_normalized",
    "is_approved",
    "is_rejected",
    "record_usable_for_spatial_analysis",
    "record_usable_for_exposure_analysis",
]


class LineageError(RuntimeError):
    """Raised when Phase 2 cannot trust the Phase 1 handoff."""

    def __init__(self, code: str, errors: list[str]):
        super().__init__(f"{code}: " + "; ".join(errors))
        self.code = code
        self.errors = errors


@dataclass(frozen=True)
class Phase1Lineage:
    phase1_run_id: str
    artifact_dir: Path
    cleaned_parquet: Path
    cleaned_parquet_sha256: str
    checksum_source: str
    expected_rows: int
    loaded_rows: int
    loaded_columns: list[str]
    phase1_status: str
    row_reconciliation_passed: bool
    manifest: dict[str, Any]
    phase1_final_report: dict[str, Any]
    row_reconciliation: dict[str, Any]
    document_claims: list[dict[str, Any]]
    data_dictionary_columns: list[str]
    checksum_match: bool
    row_count_match: bool
    raw_csv_used: bool = False

    def to_report(self) -> dict[str, Any]:
        return {
            "status": "PASS",
            "phase1_run_id": self.phase1_run_id,
            "phase1_artifact_dir": str(self.artifact_dir),
            "input_dataset_path": str(self.cleaned_parquet),
            "input_dataset_sha256": self.cleaned_parquet_sha256,
            "expected_rows": self.expected_rows,
            "loaded_rows": self.loaded_rows,
            "checksum_match": self.checksum_match,
            "row_count_match": self.row_count_match,
            "raw_csv_used": self.raw_csv_used,
            "cleaned_parquet": str(self.cleaned_parquet),
            "phase1_cleaned_parquet_sha256": self.cleaned_parquet_sha256,
            "checksum_source": self.checksum_source,
            "phase1_status": self.phase1_status,
            "row_reconciliation_passed": self.row_reconciliation_passed,
            "phase1_expected_accepted_rows": self.expected_rows,
            "phase2_loaded_rows": self.loaded_rows,
            "loaded_column_count": len(self.loaded_columns),
            "forbidden_inputs_used": [],
            "required_reports_checked": REQUIRED_PHASE1_REPORTS,
            "required_columns_checked": REQUIRED_CLEANED_COLUMNS,
        }


def repo_root(start: str | Path | None = None) -> Path:
    p = Path(start or Path.cwd()).resolve()
    for cur in [p, *p.parents]:
        if (cur / ".git").exists() or (cur / "vercel.json").exists():
            return cur
    return p


def load_config(path: str | Path = "configs/phase2.yaml",
                root: str | Path | None = None) -> dict[str, Any]:
    root_path = repo_root(root)
    p = Path(path)
    if not p.is_absolute():
        p = root_path / p
    with p.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    config["_config_path"] = str(p)
    return config


def git_commit(root: str | Path | None = None) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root(root),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return None


def config_hash(config_path: str | Path) -> str:
    return sha256_file(config_path)


def make_run_id(prefix: str = "phase2") -> str:
    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    return now.strftime(f"%Y%m%d_%H%M%S_{prefix}")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_document_claims(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return pd.read_csv(path).to_dict(orient="records")


def _resolve_path(root: Path, value: str | Path | None) -> Path | None:
    if value is None:
        return None
    p = Path(value)
    return p if p.is_absolute() else root / p


def _latest_phase1_artifact(root: Path) -> Path | None:
    base = root / "artifacts" / "phase1"
    if not base.exists():
        return None
    for candidate in sorted([p for p in base.iterdir() if p.is_dir()], reverse=True):
        final_path = candidate / "reports" / "phase1_final_report.json"
        recon_path = candidate / "reports" / "row_reconciliation.json"
        manifest_path = candidate / "manifest.json"
        if not (final_path.exists() and recon_path.exists() and manifest_path.exists()):
            continue
        try:
            final = _read_json(final_path)
            recon = _read_json(recon_path)
            manifest = _read_json(manifest_path)
        except Exception:
            continue
        status = final.get("status") or manifest.get("status")
        if status == "PASS" and bool(recon.get("passed")):
            return candidate
    return None


def resolve_phase1_artifact_dir(config: dict[str, Any],
                                root: str | Path | None = None) -> Path:
    root_path = repo_root(root)
    phase1 = config.get("phase1", {})
    run_id = str(phase1.get("run_id", "")).strip()
    if run_id == "latest":
        latest = _latest_phase1_artifact(root_path)
        if latest is None:
            raise LineageError(PHASE2_INPUT_NOT_VERIFIED, ["No valid Phase 1 PASS artifact directory exists."])
        return latest

    configured = _resolve_path(root_path, phase1.get("artifact_dir"))
    if configured is not None:
        return configured
    if run_id:
        return root_path / "artifacts" / "phase1" / run_id
    raise LineageError(PHASE2_INPUT_NOT_VERIFIED, ["phase1.run_id or phase1.artifact_dir is required."])


def _expected_checksum(artifact_dir: Path, manifest: dict[str, Any],
                       cleaned_parquet: Path) -> tuple[str, str]:
    manifest_outputs = manifest.get("outputs", {}) if isinstance(manifest.get("outputs"), dict) else {}
    for key in ("phase1_cleaned_parquet_sha256", "cleaned_parquet_sha256"):
        value = manifest.get(key) or manifest_outputs.get(key)
        if value:
            return str(value), f"manifest.{key}"

    checksums_path = artifact_dir / "checksums" / "dataset_checksums.json"
    if checksums_path.exists():
        checksums = _read_json(checksums_path)
        value = checksums.get("cleaned_parquet_sha256")
        if value:
            return str(value), "checksums/dataset_checksums.json"

    return sha256_file(cleaned_parquet), "computed_supplement"


def _expected_rows(final_report: dict[str, Any],
                   row_reconciliation: dict[str, Any]) -> int | None:
    summary = final_report.get("summary", {})
    value = summary.get("accepted_rows", row_reconciliation.get("accepted_rows"))
    return int(value) if value is not None else None


def validate_phase1_lineage(config: dict[str, Any],
                            root: str | Path | None = None) -> Phase1Lineage:
    root_path = repo_root(root)
    phase1 = config.get("phase1", {})
    artifact_dir = resolve_phase1_artifact_dir(config, root_path)
    reports_dir = artifact_dir / "reports"
    errors: list[str] = []

    manifest_path = artifact_dir / "manifest.json"
    if not artifact_dir.exists():
        errors.append(f"Missing Phase 1 artifact directory: {artifact_dir}")
    if not manifest_path.exists():
        errors.append(f"Missing Phase 1 manifest: {manifest_path}")
    for report in REQUIRED_PHASE1_REPORTS:
        if not (reports_dir / report).exists():
            errors.append(f"Missing Phase 1 report: {reports_dir / report}")
    if errors:
        raise LineageError(PHASE2_INPUT_NOT_VERIFIED, errors)

    manifest = _read_json(manifest_path)
    final_report = _read_json(reports_dir / "phase1_final_report.json")
    row_reconciliation = _read_json(reports_dir / "row_reconciliation.json")
    document_claims = _read_document_claims(reports_dir / "document_claims_comparison.csv")
    data_dictionary = pd.read_csv(reports_dir / "data_dictionary.csv")

    required_status = phase1.get("required_status", "PASS")
    phase1_status = str(final_report.get("status") or manifest.get("status"))
    if required_status and phase1_status != required_status:
        errors.append(f"Phase 1 status is {phase1_status!r}, expected {required_status!r}.")

    if phase1.get("require_row_reconciliation", True):
        if not bool(row_reconciliation.get("passed")):
            errors.append("Phase 1 row reconciliation did not pass.")

    cleaned_parquet = _resolve_path(root_path, phase1.get("cleaned_parquet"))
    if cleaned_parquet is None:
        output_path = final_report.get("outputs", {}).get("cleaned_parquet")
        cleaned_parquet = _resolve_path(root_path, output_path)
    if cleaned_parquet is None:
        errors.append("Phase 1 cleaned parquet path is not configured and not present in the final report.")
    elif not cleaned_parquet.exists():
        errors.append(f"Missing cleaned parquet: {cleaned_parquet}")
    if errors:
        raise LineageError(PHASE2_INPUT_NOT_VERIFIED, errors)

    assert cleaned_parquet is not None
    actual_checksum = sha256_file(cleaned_parquet)
    expected_checksum, checksum_source = _expected_checksum(artifact_dir, manifest, cleaned_parquet)
    checksum_match = actual_checksum == expected_checksum
    if not checksum_match:
        errors.append(
            "Cleaned parquet checksum mismatch: "
            f"expected {expected_checksum}, got {actual_checksum}."
        )

    try:
        df = pd.read_parquet(cleaned_parquet)
    except Exception as exc:
        errors.append(f"Cleaned parquet is not readable: {type(exc).__name__}: {exc}")
        raise LineageError(PHASE2_INPUT_NOT_VERIFIED, errors) from exc

    expected_row_count = _expected_rows(final_report, row_reconciliation)
    if expected_row_count is None:
        errors.append("Could not determine Phase 1 accepted row count.")
        expected_row_count = -1
    row_count_match = len(df) == expected_row_count
    if expected_row_count is not None and not row_count_match:
        errors.append(f"Phase 1 accepted rows {expected_row_count} != parquet rows {len(df)}.")

    id_present = "record_id_normalized" in df.columns or "id" in df.columns
    if not id_present:
        errors.append("Missing record identifier: expected record_id_normalized or id.")
    missing_columns = [c for c in REQUIRED_CLEANED_COLUMNS if c not in df.columns]
    if missing_columns:
        errors.append("Missing required cleaned columns: " + ", ".join(missing_columns))

    if errors:
        raise LineageError(PHASE2_INPUT_NOT_VERIFIED, errors)

    return Phase1Lineage(
        phase1_run_id=str(final_report.get("run_id") or manifest.get("run_id")),
        artifact_dir=artifact_dir,
        cleaned_parquet=cleaned_parquet,
        cleaned_parquet_sha256=actual_checksum,
        checksum_source=checksum_source,
        expected_rows=int(expected_row_count),
        loaded_rows=len(df),
        loaded_columns=list(df.columns),
        phase1_status=phase1_status,
        row_reconciliation_passed=bool(row_reconciliation.get("passed")),
        manifest=manifest,
        phase1_final_report=final_report,
        row_reconciliation=row_reconciliation,
        document_claims=document_claims,
        data_dictionary_columns=list(data_dictionary.columns),
        checksum_match=checksum_match,
        row_count_match=row_count_match,
    )


def python_environment_report() -> dict[str, Any]:
    return {
        "python_version": sys.version,
        "pandas_version": pd.__version__,
    }
