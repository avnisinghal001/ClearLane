"""
ml.v3/cache/cache.py — the unified cache facade.

`get_or_fetch(ns, key, fetch_fn, live, ttl)` is the only call sites use. Lookup
order:

  STATIC (live=False):  in-process memo -> local JSON -> MongoDB -> fetch_fn()
                        on a fetch (or a Mongo hit with no local copy) it publishes
                        a CacheEvent so the value lands in BOTH local JSON + Mongo.

  LIVE   (live=True):   short in-process memo -> MongoDB (fresh only) -> fetch_fn()
                        a fetch publishes a CacheEvent -> Mongo ONLY, with a TTL.

Writes go through the EventBus (local + mongo sinks) and are batched: the bus
auto-flushes every config.CACHE_FLUSH_EVERY events, and callers should call
`flush()` once at the end of a stage.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # ml.v3
import config as C          # noqa: E402

from .bus import CacheEvent, EventBus      # noqa: E402
from .local_store import LocalJSONStore    # noqa: E402
from .mongo_store import MongoStore        # noqa: E402


class MapplsCache:
    def __init__(self):
        self.bus = EventBus()
        self.local = LocalJSONStore()
        self.mongo = MongoStore()
        self.bus.subscribe(self.local)      # static -> local JSON
        self.bus.subscribe(self.mongo)      # static + live -> MongoDB
        self._mem: dict[str, object] = {}           # static memo (forever)
        self._mem_live: dict[str, tuple] = {}       # live memo: key -> (value, exp)
        self._pending = 0

    # ------------------------------------------------------------------ #
    def get_or_fetch(self, ns: str, key: str, fetch_fn, live: bool = False, ttl=None):
        ck = f"{ns}|{key}"
        now = time.time()

        if live:
            ent = self._mem_live.get(ck)
            if ent and now < ent[1]:
                return ent[0]
            mv = self.mongo.get(ns, key, live=True)
            if mv is not None:
                self._mem_live[ck] = (mv, now + C.CACHE_MEM_LIVE_TTL_S)
                return mv
        else:
            if ck in self._mem:
                return self._mem[ck]
            lv = self.local.get(ns, key)
            if lv is not None:
                self._mem[ck] = lv
                return lv
            mv = self.mongo.get(ns, key, live=False)
            if mv is not None:                       # backfill local from Mongo
                self._mem[ck] = mv
                self.bus.publish(CacheEvent(ns, key, mv, live=False))
                self._maybe_flush()
                return mv

        # --- miss: fetch fresh -------------------------------------------- #
        val = fetch_fn()
        if val is None:
            return None
        if live:
            memo_exp = now + min(ttl or C.CACHE_LIVE_TTL_S, C.CACHE_MEM_LIVE_TTL_S)
            self._mem_live[ck] = (val, memo_exp)
            self.bus.publish(CacheEvent(ns, key, val, live=True, ttl=ttl))
        else:
            self._mem[ck] = val
            self.bus.publish(CacheEvent(ns, key, val, live=False))
        self._maybe_flush()
        return val

    # ------------------------------------------------------------------ #
    def _maybe_flush(self):
        self._pending += 1
        if self._pending >= C.CACHE_FLUSH_EVERY:
            self.flush()

    def flush(self):
        self.bus.flush()
        self._pending = 0

    def sync_local_to_mongo(self) -> int:
        """Push every locally-cached STATIC entry into MongoDB (durable mirror)."""
        n = 0
        for ns, key, value in self.local.iter_all():
            self.bus.publish(CacheEvent(ns, key, value, live=False))
            n += 1
        self.flush()
        return n

    def stats(self) -> dict:
        return {"mem_static": len(self._mem), "mem_live": len(self._mem_live),
                **self.mongo.stats()}
