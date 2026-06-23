from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


def superzone_status(config: dict[str, Any], root: str | Path) -> dict[str, Any]:
    cfg = config.get("superzones", {})
    enabled = bool(cfg.get("enabled", False))
    path_value = cfg.get("definitions_path")
    path = Path(path_value) if path_value else None
    if path is not None and not path.is_absolute():
        path = Path(root) / path

    if not enabled:
        return {
            "status": "DISABLED",
            "enabled": False,
            "definitions_path": str(path) if path else None,
        }
    if path is None or not path.exists():
        message = f"Superzones are enabled but definitions are missing: {path}"
        if cfg.get("fail_when_claimed_but_missing", True):
            raise FileNotFoundError(message)
        return {"status": "WARN", "enabled": True, "message": message}
    return {"status": "PASS", "enabled": True, "definitions_path": str(path)}


def assign_superzones(h3_table: pd.DataFrame, mapping: pd.DataFrame,
                      h3_col: str = "h3_res10",
                      superzone_col: str = "superzone_id") -> pd.DataFrame:
    required = [h3_col, superzone_col]
    missing = [c for c in required if c not in mapping.columns]
    if missing:
        raise ValueError("Missing superzone mapping columns: " + ", ".join(missing))
    return h3_table.merge(mapping[[h3_col, superzone_col]], on=h3_col, how="left")
