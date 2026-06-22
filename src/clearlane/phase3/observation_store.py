"""Partitioned traffic-observation store with idempotency.

Observations are stored under
  data/live/mappls_traffic_observations/observation_date=YYYY-MM-DD/part.parquet

Idempotency key: (directed_segment_id, observation_bucket_ist, provider, data_mode).
Re-running the same poll in the same bucket updates rather than duplicates.
Invalid observations are retained (for audit) but excluded from metrics by the
`is_valid_observation` flag. REPLAY rows carry data_mode=REPLAY.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

IDEMPOTENCY_FIELDS = ["directed_segment_id", "observation_bucket_ist", "provider", "data_mode"]


def observation_id(row: dict[str, Any]) -> str:
    key = "|".join(str(row.get(f, "")) for f in IDEMPOTENCY_FIELDS)
    return "obs_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]


class ObservationStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _partition_path(self, observation_date: str) -> Path:
        return self.root / f"observation_date={observation_date}" / "part.parquet"

    def write(self, observations: Iterable[dict[str, Any]]) -> dict[str, Any]:
        rows = list(observations)
        for r in rows:
            r.setdefault("observation_id", observation_id(r))
        if not rows:
            return {"written": 0, "partitions": [], "duplicates_replaced": 0}

        df_new = pd.DataFrame(rows)
        if "observation_date" not in df_new.columns:
            df_new["observation_date"] = df_new["observed_at_ist"].astype(str).str.slice(0, 10)

        written = 0
        replaced = 0
        partitions = []
        for date, group in df_new.groupby("observation_date"):
            path = self._partition_path(str(date))
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                existing = pd.read_parquet(path)
                before = len(existing)
                # drop existing rows that collide on the idempotency key
                merged_keys = set(
                    tuple(r) for r in group[IDEMPOTENCY_FIELDS].astype(str).itertuples(index=False, name=None)
                )
                mask = existing[IDEMPOTENCY_FIELDS].astype(str).apply(tuple, axis=1).isin(merged_keys)
                replaced += int(mask.sum())
                existing = existing[~mask]
                combined = pd.concat([existing, group], ignore_index=True)
            else:
                combined = group.reset_index(drop=True)
            combined.to_parquet(path, index=False)
            written += len(group)
            partitions.append(str(path))
        return {"written": written, "partitions": partitions, "duplicates_replaced": replaced}

    def read_all(self) -> pd.DataFrame:
        if not self.root.exists():
            return pd.DataFrame()
        parts = sorted(self.root.glob("observation_date=*/part.parquet"))
        if not parts:
            return pd.DataFrame()
        return pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)

    def valid_live_eta_samples(self, directed_segment_id: str) -> list[tuple[Any, float]]:
        """Return (observed_at, live_eta_duration_s) for VALID LIVE observations only.

        REPLAY observations are excluded so they never update the production baseline.
        """
        df = self.read_all()
        if df.empty:
            return []
        mask = (
            (df["directed_segment_id"] == directed_segment_id)
            & (df.get("is_valid_observation") == True)  # noqa: E712
            & (df.get("data_mode") == "LIVE")
        )
        sub = df[mask]
        out = []
        for _, r in sub.iterrows():
            dur = r.get("live_eta_duration_s")
            ts = pd.to_datetime(r.get("observed_at_ist"), errors="coerce")
            if pd.notna(dur) and pd.notna(ts):
                out.append((ts.to_pydatetime(), float(dur)))
        return out
