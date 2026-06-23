from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd


def json_safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [json_safe(v) for v in obj]
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if pd.isna(obj) and obj is not None and not isinstance(obj, (str, bytes, bool)):
        return None
    return obj


def write_json(path: str | Path, obj: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(json_safe(obj), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def dataframe_fingerprint(df: pd.DataFrame) -> str:
    stable = df.copy()
    stable = stable.reindex(sorted(stable.columns), axis=1)
    csv = stable.fillna("<NA>").astype(str).to_csv(index=False, lineterminator="\n")
    return hashlib.sha256(csv.encode("utf-8")).hexdigest()


def mask_value(value: object, keep: int = 4) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]
    return f"{text[:keep]}...#{digest}"

