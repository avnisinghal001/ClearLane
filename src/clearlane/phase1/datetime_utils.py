from __future__ import annotations

import re
from zoneinfo import ZoneInfo

import pandas as pd

from .category_normalization import is_null_like

TZ_RE = re.compile(r"(Z|[+-]\d{2}(:?\d{2})?)$")


def timestamp_has_timezone(value: object) -> bool:
    if is_null_like(value):
        return False
    return bool(TZ_RE.search(str(value).strip()))


def parse_timestamp_value(value: object, *, source_timezone: str,
                          canonical_timezone: str, dayfirst: bool = False) -> pd.Timestamp | pd.NaT:
    if is_null_like(value):
        return pd.NaT
    ts = pd.to_datetime(str(value).strip(), errors="coerce", dayfirst=dayfirst)
    if pd.isna(ts):
        return pd.NaT
    source_tz = ZoneInfo(source_timezone)
    canonical_tz = ZoneInfo(canonical_timezone)
    if ts.tzinfo is None:
        ts = ts.tz_localize(source_tz)
    else:
        ts = ts.tz_convert(canonical_tz)
    return ts.tz_convert(canonical_tz)


def parse_datetime_series(series: pd.Series, *, source_timezone: str,
                          canonical_timezone: str, dayfirst: bool = False) -> tuple[pd.Series, pd.Series, dict, pd.Series]:
    raw_non_null = ~series.map(is_null_like).astype(bool)
    clean = series.astype("string").where(raw_non_null, pd.NA)
    source_tz = ZoneInfo(source_timezone)
    canonical_tz = ZoneInfo(canonical_timezone)

    if int(raw_non_null.sum()) == 0:
        parsed = pd.Series([pd.NaT] * len(series), index=series.index, dtype="object")
    else:
        aware_flags = series[raw_non_null].map(lambda v: bool(timestamp_has_timezone(v))).astype(bool)
        if bool(aware_flags.all()):
            parsed = pd.to_datetime(clean, errors="coerce", dayfirst=dayfirst, utc=True).dt.tz_convert(canonical_tz)
        elif not bool(aware_flags.any()):
            tmp = pd.to_datetime(clean, errors="coerce", dayfirst=dayfirst)
            parsed = tmp.dt.tz_localize(source_tz, nonexistent="NaT", ambiguous="NaT").dt.tz_convert(canonical_tz)
        else:
            parsed = series.map(lambda v: parse_timestamp_value(
                v,
                source_timezone=source_timezone,
                canonical_timezone=canonical_timezone,
                dayfirst=dayfirst,
            )).astype("object")

    valid = parsed.notna() | ~raw_non_null
    tz_flags = series[raw_non_null].map(lambda v: bool(timestamp_has_timezone(v)))
    aware_count = int(tz_flags.sum()) if len(tz_flags) else 0
    naive_count = int(raw_non_null.sum() - aware_count)
    report = {
        "raw_non_null": int(raw_non_null.sum()),
        "aware_values": aware_count,
        "naive_values": naive_count,
        "invalid_non_null": int((raw_non_null & parsed.isna()).sum()),
        "source_timezone_for_naive": source_timezone,
        "canonical_timezone": canonical_timezone,
        "used_utc_true_blindly": False,
    }
    iso = parsed.map(lambda v: v.isoformat() if pd.notna(v) else None)
    return iso, valid, report, parsed
