from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .category_normalization import is_null_like
from .reporting import mask_value, write_json

HIGH_CARDINALITY = {"id", "vehicle_number", "device_id", "created_by_id"}


def _series_profile(name: str, s: pd.Series) -> dict:
    str_s = s.astype("string")
    non_null = ~str_s.map(is_null_like)
    numeric = pd.to_numeric(str_s.where(non_null), errors="coerce")
    lengths = str_s.where(non_null).dropna().map(len)
    return {
        "column": name,
        "raw_dtype": str(s.dtype),
        "null_count": int((~non_null).sum()),
        "null_percentage": round(float((~non_null).mean() * 100), 4) if len(s) else 0.0,
        "empty_string_count": int(str_s.fillna("").eq("").sum()),
        "unique_count": int(str_s.where(non_null).nunique(dropna=True)),
        "min_string_length": int(lengths.min()) if len(lengths) else None,
        "max_string_length": int(lengths.max()) if len(lengths) else None,
        "min_numeric_value": float(numeric.min()) if numeric.notna().any() else None,
        "max_numeric_value": float(numeric.max()) if numeric.notna().any() else None,
    }


def build_profile(df: pd.DataFrame, *, name: str) -> dict:
    cols = [_series_profile(c, df[c]) for c in df.columns if c != "source_row_number"]
    return {
        "profile_name": name,
        "row_count": int(len(df)),
        "column_count": int(len([c for c in df.columns if c != "source_row_number"])),
        "column_order": [c for c in df.columns if c != "source_row_number"],
        "columns": cols,
    }


def write_raw_profile_reports(raw: pd.DataFrame, reports_dir: str | Path) -> dict:
    reports = Path(reports_dir)
    reports.mkdir(parents=True, exist_ok=True)
    profile = build_profile(raw, name="raw")
    write_json(reports / "raw_profile.json", profile)

    columns = []
    value_examples = {}
    for col in [c for c in raw.columns if c != "source_row_number"]:
        p = next(r for r in profile["columns"] if r["column"] == col)
        columns.append(p)
        s = raw[col].astype("string")
        non_null = s[~s.map(is_null_like)]
        if col in HIGH_CARDINALITY:
            top = non_null.value_counts().head(1)
            bottom = non_null.value_counts().tail(1)
            value_examples[col] = {
                "unique_count": int(non_null.nunique(dropna=True)),
                "top_frequency_count": int(top.iloc[0]) if len(top) else 0,
                "bottom_frequency_count": int(bottom.iloc[0]) if len(bottom) else 0,
                "sample_anonymized_values": [mask_value(v) for v in non_null.drop_duplicates().head(5)],
            }
        else:
            value_examples[col] = non_null.drop_duplicates().head(10).tolist()

    pd.DataFrame(columns).to_csv(reports / "raw_schema.csv", index=False)
    pd.DataFrame([{
        "column": c["column"],
        "null_count": c["null_count"],
        "null_percentage": c["null_percentage"],
        "empty_string_count": c["empty_string_count"],
    } for c in columns]).to_csv(reports / "raw_null_report.csv", index=False)
    pd.DataFrame([{
        "column": c["column"],
        "unique_count": c["unique_count"],
    } for c in columns]).to_csv(reports / "raw_unique_counts.csv", index=False)
    sample = raw.head(25).copy()
    for col in HIGH_CARDINALITY & set(sample.columns):
        sample[col] = sample[col].map(mask_value)
    sample.to_csv(reports / "raw_sample_rows.csv", index=False)
    (reports / "raw_value_examples.json").write_text(
        json.dumps(value_examples, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return profile

