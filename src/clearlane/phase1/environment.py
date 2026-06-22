from __future__ import annotations

import importlib
import importlib.metadata
import platform
import shutil
import sys
from pathlib import Path

from .reporting import write_json

REQUIRED_PACKAGES = ["pandas", "numpy", "pyarrow", "pydantic", "yaml", "pytest", "matplotlib"]
PACKAGE_DISTRIBUTIONS = {"yaml": "PyYAML"}


def validate_environment(report_path: str | Path | None = None) -> dict:
    packages: dict[str, dict] = {}
    missing = []
    for mod_name in REQUIRED_PACKAGES:
        dist_name = PACKAGE_DISTRIBUTIONS.get(mod_name, mod_name)
        try:
            importlib.import_module(mod_name)
            version = importlib.metadata.version(dist_name)
            packages[dist_name] = {"available": True, "version": version}
        except Exception as exc:
            packages[dist_name] = {"available": False, "error": type(exc).__name__}
            missing.append(dist_name)
    report = {
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "uv_available": shutil.which("uv") is not None,
        "packages": packages,
        "status": "PASS" if not missing else "FAIL",
        "missing": missing,
        "phase1_requires_mappls": False,
        "phase1_requires_h3_or_ml_stack": False,
    }
    if report_path is not None:
        write_json(report_path, report)
    return report

