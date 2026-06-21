"""
ml.v3/cache/mongo_store.py — MongoDB sink.

Two collections:
  * config.CACHE_STATIC_COLLECTION — durable, no expiry (POI/geocode/snap/...).
  * config.CACHE_LIVE_COLLECTION   — TTL: each doc carries `expireAt`; a TTL index
    (expireAfterSeconds=0) makes Mongo auto-delete it once it lapses.

Doc shape: { _id: "<ns>|<key>", ns, key, value, ts[, expireAt] }.

Connection is LAZY (first use) and tolerant of MONGOURI / MONGODB_URI. If Mongo is
unreachable / pymongo absent, every method becomes a safe no-op so the pipeline
keeps working from the local-JSON tier (offline-first).
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # ml.v3
import config as C          # noqa: E402

from .bus import CacheEvent  # noqa: E402


def _env(*names):
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return None


def _now():
    return datetime.now(timezone.utc)


class MongoStore:
    def __init__(self):
        self._db = None
        self._ok: bool | None = None        # None=untried, True/False=resolved
        self._buf_static: list[tuple] = []   # (id, ns, key, value)
        self._buf_live: list[tuple] = []     # (id, ns, key, value, ttl)

    def _connect(self) -> bool:
        if self._ok is not None:
            return self._ok
        try:
            from pymongo import MongoClient
            uri = _env(*C.MONGO_URI_ENVS)
            if not uri:
                self._ok = False
                return False
            client = MongoClient(uri, serverSelectionTimeoutMS=6000)
            client.admin.command("ping")
            self._db = client[_env(*C.MONGO_DB_ENVS) or C.MONGO_DB_DEFAULT]
            # TTL index so live entries self-delete once expireAt passes.
            self._db[C.CACHE_LIVE_COLLECTION].create_index("expireAt", expireAfterSeconds=0)
            self._ok = True
        except Exception:
            self._ok = False
        return self._ok

    def available(self) -> bool:
        return self._connect()

    # read API ------------------------------------------------------------- #
    def get(self, ns: str, key: str, live: bool = False):
        if not self._connect():
            return None
        coll = self._db[C.CACHE_LIVE_COLLECTION if live else C.CACHE_STATIC_COLLECTION]
        try:
            doc = coll.find_one({"_id": f"{ns}|{key}"})
        except Exception:
            return None
        if not doc:
            return None
        if live:                                   # belt-and-suspenders vs TTL lag
            exp = doc.get("expireAt")
            if exp is not None:
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
                if exp < _now():
                    return None
        return doc.get("value")

    # sink API ------------------------------------------------------------- #
    def handle(self, event: CacheEvent) -> None:
        _id = f"{event.ns}|{event.key}"
        if event.live:
            self._buf_live.append((_id, event.ns, event.key, event.value, event.ttl))
        else:
            self._buf_static.append((_id, event.ns, event.key, event.value))

    def flush(self) -> None:
        if not self._connect():
            self._buf_static.clear(); self._buf_live.clear()
            return
        try:
            from pymongo import UpdateOne
            if self._buf_static:
                ops = [UpdateOne({"_id": i},
                                 {"$set": {"ns": ns, "key": k, "value": v, "ts": _now()}},
                                 upsert=True)
                       for (i, ns, k, v) in self._buf_static]
                self._db[C.CACHE_STATIC_COLLECTION].bulk_write(ops, ordered=False)
                self._buf_static.clear()
            if self._buf_live:
                now = _now()
                ops = []
                for (i, ns, k, v, ttl) in self._buf_live:
                    exp = now + timedelta(seconds=ttl or C.CACHE_LIVE_TTL_S)
                    ops.append(UpdateOne(
                        {"_id": i},
                        {"$set": {"ns": ns, "key": k, "value": v, "ts": now, "expireAt": exp}},
                        upsert=True))
                self._db[C.CACHE_LIVE_COLLECTION].bulk_write(ops, ordered=False)
                self._buf_live.clear()
        except Exception:
            # never let a cache write break the caller
            self._buf_static.clear(); self._buf_live.clear()

    def stats(self) -> dict:
        if not self._connect():
            return {"mongo": "unavailable"}
        try:
            return {"mongo": "ok",
                    "static": self._db[C.CACHE_STATIC_COLLECTION].estimated_document_count(),
                    "live": self._db[C.CACHE_LIVE_COLLECTION].estimated_document_count()}
        except Exception:
            return {"mongo": "error"}
