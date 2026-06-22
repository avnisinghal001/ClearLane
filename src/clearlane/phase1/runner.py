from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yaml

from .cleaning import clean_dataframe
from .discovery import discover_raw_file
from .environment import validate_environment
from .fingerprint import physical_line_count, sha256_file
from .profiling import write_raw_profile_reports
from .reporting import dataframe_fingerprint, write_json
from .schema import validate_schema


def _repo_root(start: str | Path | None = None) -> Path:
    p = Path(start or Path.cwd()).resolve()
    for cur in [p, *p.parents]:
        if (cur / ".git").exists() or (cur / "vercel.json").exists():
            return cur
    return p


def _load_config(path: str | Path, root: Path) -> dict:
    p = Path(path)
    if not p.is_absolute():
        p = root / p
    with p.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["_config_path"] = str(p)
    return cfg


def _git_commit(root: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return None


def _manifest_base(config: dict, raw_path: Path, run_id: str, started_at: str) -> dict:
    stat = raw_path.stat()
    return {
        "run_id": run_id,
        "phase": "phase1",
        "input_path": config["input"]["raw_csv"],
        "input_absolute_path": str(raw_path.resolve()),
        "input_size_bytes": stat.st_size,
        "input_modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "input_physical_line_count": physical_line_count(raw_path),
        "input_sha256_before": sha256_file(raw_path),
        "input_sha256_after": None,
        "raw_file_unchanged": None,
        "python_version": sys.version,
        "pandas_version": pd.__version__,
        "git_commit": None,
        "config_path": config["_config_path"],
        "timestamp_assumptions": {
            "source_timezone_for_naive_values": config["datetime"]["source_timezone"],
            "canonical_timezone": config["datetime"]["canonical_timezone"],
            "created_datetime_is_incident_time": "not assumed",
            "hour_is_diagnostic_only": True,
        },
        "started_at": started_at,
        "completed_at": None,
        "status": "running",
    }


def run_phase1(config_path: str | Path = "configs/phase1.yaml",
               root: str | Path | None = None) -> dict:
    root_path = _repo_root(root)
    config = _load_config(config_path, root_path)
    tz = ZoneInfo(config["datetime"]["canonical_timezone"])
    started = datetime.now(tz)
    run_id = started.strftime("%Y%m%d_%H%M%S_phase1")

    raw_path = discover_raw_file(config, root_path)
    artifact_root = root_path / config["outputs"]["artifact_root"] / run_id
    reports_dir = artifact_root / "reports"
    checksums_dir = artifact_root / "checksums"
    logs_dir = artifact_root / "logs"
    for d in (reports_dir, checksums_dir, logs_dir, artifact_root / "plots"):
        d.mkdir(parents=True, exist_ok=True)

    manifest = _manifest_base(config, raw_path, run_id, started.isoformat())
    manifest["git_commit"] = _git_commit(root_path)
    write_json(artifact_root / "manifest.json", manifest)

    final_status = "FAIL"
    warnings: list[str] = []
    errors: list[str] = []
    t0 = time.time()
    try:
        env = validate_environment(reports_dir / "environment_report.json")
        if env["status"] != "PASS":
            errors.append("Environment validation failed.")
        if not env.get("uv_available"):
            warnings.append("uv is not available; recorded as a warning, not a Phase 1 blocker.")

        raw = pd.read_csv(
            raw_path,
            dtype="string",
            keep_default_na=False,
            sep=config["input"].get("delimiter", ","),
            encoding=config["input"].get("encoding", "utf-8"),
            low_memory=False,
        )
        raw.insert(0, "source_row_number", range(2, len(raw) + 2))

        write_raw_profile_reports(raw, reports_dir)
        schema_report, missing_critical, extra_cols = validate_schema(raw)
        schema_report.to_csv(reports_dir / "schema_validation.csv", index=False)
        pd.DataFrame({"extra_column": extra_cols}).to_csv(reports_dir / "extra_columns_report.csv", index=False)
        if missing_critical:
            errors.append("Missing critical columns: " + ", ".join(missing_critical))

        result = clean_dataframe(
            raw,
            config,
            reports_dir,
            root_path / config["outputs"]["quarantine_dir"],
        )

        interim_parquet = root_path / config["outputs"]["cleaned_parquet"]
        interim_csv = root_path / config["outputs"]["cleaned_csv"]
        interim_parquet.parent.mkdir(parents=True, exist_ok=True)
        result.accepted.to_parquet(interim_parquet, index=False)
        result.accepted.to_csv(interim_csv, index=False)

        write_json(checksums_dir / "dataset_checksums.json", {
            "cleaned_dataframe_fingerprint": dataframe_fingerprint(result.accepted),
            "cleaned_parquet_sha256": sha256_file(interim_parquet),
            "cleaned_csv_sha256": sha256_file(interim_csv),
            "raw_sha256": manifest["input_sha256_before"],
        })

        if not result.reports["row_reconciliation"]["passed"]:
            errors.append("Row reconciliation failed.")

        final_status = "FAIL" if errors else ("WARN" if warnings else "PASS")
        final = {
            "run_id": run_id,
            "status": final_status,
            "errors": errors,
            "warnings": warnings,
            "duration_seconds": round(time.time() - t0, 3),
            "outputs": {
                "cleaned_parquet": str(interim_parquet),
                "cleaned_csv": str(interim_csv),
                "quarantine_dir": str(root_path / config["outputs"]["quarantine_dir"]),
                "artifact_dir": str(artifact_root),
            },
            "summary": {
                **result.reports["cleaning_report"],
                "parking_related_percentage": result.reports["parking_summary"]["parking_related_percentage"],
                "hour_axis_conclusion": result.reports["temporal_artifact_report"]["conclusion"],
            },
            "phase1_excludes_later_ml": [
                "H3", "Mappls", "PIC", "forecasting", "dispatch", "online learning",
            ],
        }
        write_json(reports_dir / "phase1_final_report.json", final)
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
        final_status = "FAIL"
        write_json(reports_dir / "phase1_final_report.json", {
            "run_id": run_id,
            "status": final_status,
            "errors": errors,
            "warnings": warnings,
            "duration_seconds": round(time.time() - t0, 3),
        })
        raise
    finally:
        after = sha256_file(raw_path)
        manifest["input_sha256_after"] = after
        manifest["raw_file_unchanged"] = after == manifest["input_sha256_before"]
        manifest["completed_at"] = datetime.now(tz).isoformat()
        manifest["status"] = final_status
        manifest["errors"] = errors
        manifest["warnings"] = warnings
        write_json(artifact_root / "manifest.json", manifest)

    return {
        "run_id": run_id,
        "status": final_status,
        "artifact_dir": str(artifact_root),
        "reports_dir": str(reports_dir),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run ClearLane Phase 1 data foundation.")
    parser.add_argument("--config", default="configs/phase1.yaml")
    args = parser.parse_args(argv)
    result = run_phase1(args.config)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] in {"PASS", "WARN"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

