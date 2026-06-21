"""
ml.v3/cache/local_store.py — local-JSON sink for STATIC namespaces.

One JSON file per namespace under config.CACHE_LOCAL_DIR, e.g.
`data/processed/v3/cache/static/nearby.json` = { "<key>": <value>, ... }.

This is the fast, offline, deterministic tier. LIVE events are ignored here (they
live in MongoDB only). Writes are buffered in memory and flushed on `flush()`.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # ml.v3
import config as C          # noqa: E402

from .bus import CacheEvent  # noqa: E402


class LocalJSONStore:
    def __init__(self, base_dir: Path | None = None):
        self.base = Path(base_dir or C.CACHE_LOCAL_DIR)
        self.base.mkdir(parents=True, exist_ok=True)
        self._mem: dict[str, dict] = {}      # ns -> {key: value}
        self._dirty: set[str] = set()

    def _load(self, ns: str) -> dict:
        if ns not in self._mem:
            f = self.base / f"{ns}.json"
            try:
                self._mem[ns] = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
            except Exception:
                self._mem[ns] = {}
        return self._mem[ns]

    # read API ------------------------------------------------------------- #
    def get(self, ns: str, key: str):
        return self._load(ns).get(key)

    # sink API ------------------------------------------------------------- #
    def handle(self, event: CacheEvent) -> None:
        if event.live:                       # live values are NOT cached locally
            return
        self._load(event.ns)[event.key] = event.value
        self._dirty.add(event.ns)

    def flush(self) -> None:
        for ns in list(self._dirty):
            try:
                (self.base / f"{ns}.json").write_text(
                    json.dumps(self._mem.get(ns, {}), separators=(",", ":")),
                    encoding="utf-8")
            except Exception:
                pass
        self._dirty.clear()

    # iterate every cached static entry (used by sync_local_to_mongo) ------ #
    def iter_all(self):
        for f in sorted(self.base.glob("*.json")):
            ns = f.stem
            for key, value in self._load(ns).items():
                yield ns, key, value
