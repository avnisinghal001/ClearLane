from __future__ import annotations

from pathlib import Path


def discover_raw_file(config: dict, root: str | Path) -> Path:
    root = Path(root)
    configured = Path(config["input"]["raw_csv"])
    raw = configured if configured.is_absolute() else root / configured
    if not raw.exists():
        raise FileNotFoundError(f"Configured raw CSV not found: {raw}")
    if raw.is_dir():
        raise IsADirectoryError(f"Configured raw CSV is a directory: {raw}")
    return raw

