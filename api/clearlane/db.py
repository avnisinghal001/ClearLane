"""
MongoDB data layer for ClearLane (Vercel-ready).

Vercel's serverless filesystem is READ-ONLY and ephemeral, so every piece of
mutable state (complaints, dispatches, officer feedback, force rosters, auth
sessions) and the large precomputed pipeline artifacts live in MongoDB. The
client is cached at module scope so warm invocations reuse a single connection
pool.

Configuration (env):
  MONGODB_URI   mongodb+srv://...  (required for Mongo mode; MONGO_URL also read)
  MONGODB_DB    database name      (default: "clearlane")

When MONGODB_URI is unset we run in "filesystem" mode (local dev without Mongo):
artifact reads fall back to data/processed and frontend/public/demo; write
endpoints degrade to a clear 503 so the offline-first frontend keeps working.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

try:                                       # pymongo is only needed in Mongo mode
    from pymongo import MongoClient, ReturnDocument
    _HAS_PYMONGO = True
except Exception:                          # pragma: no cover - local FS-only dev
    MongoClient = None  # type: ignore
    ReturnDocument = None  # type: ignore
    _HAS_PYMONGO = False

# repo root (…/ClearLane) — used for the filesystem fallback
ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv() -> None:
    """Local-dev convenience: populate os.environ from .env / backend/.env /
    ml.v3/.env so `uvicorn` picks up MONGODB_URI + the Mappls keys without extra
    steps. On Vercel the platform injects env vars directly and these files don't
    exist, so this no-ops. (ml.v3/.env carries MYMAPINDIA_STATIC_API_KEY — the
    browser Map-SDK key the v3 frontend needs from /api/config.)"""
    for p in (ROOT / ".env", ROOT / "backend" / ".env", ROOT / "ml.v3" / ".env"):
        if not p.exists():
            continue
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        except Exception:                   # pragma: no cover
            pass


_load_dotenv()

# accept the common spellings so deployment env vars "just work"
MONGODB_URI = (os.environ.get("MONGODB_URI") or os.environ.get("MONGO_URL")
               or os.environ.get("MONGOURI") or os.environ.get("MONGO_URI"))
MONGODB_DB = (os.environ.get("MONGODB_DB") or os.environ.get("MONGO_DB")
              or "clearlane")
ARTIFACTS_COLLECTION = "artifacts"

_client = None
_artifact_cache: dict[str, object] = {}


def mongo_enabled() -> bool:
    return bool(MONGODB_URI) and _HAS_PYMONGO


def get_client():
    """Return a cached MongoClient, or None when Mongo is not configured."""
    global _client
    if not mongo_enabled():
        return None
    if _client is None:
        _client = MongoClient(
            MONGODB_URI,
            appname="clearlane",
            serverSelectionTimeoutMS=8000,
            connectTimeoutMS=8000,
            retryWrites=True,
            tz_aware=False,
        )
    return _client


def get_db():
    client = get_client()
    return client[MONGODB_DB] if client is not None else None


def col(name: str):
    """Return a collection handle, or None when Mongo is not configured."""
    db = get_db()
    return db[name] if db is not None else None


def next_id(name: str) -> int:
    """Atomic auto-increment integer id (mirrors SQLite AUTOINCREMENT)."""
    c = col("counters")
    if c is None:
        raise RuntimeError("MongoDB not configured")
    doc = c.find_one_and_update(
        {"_id": name}, {"$inc": {"seq": 1}},
        upsert=True, return_document=ReturnDocument.AFTER,
    )
    return int(doc["seq"])


# --------------------------------------------------------------------------- #
# Artifact store (the precomputed pipeline JSON)
# --------------------------------------------------------------------------- #
def _fs_artifact(name: str):
    for d in (ROOT / "data" / "processed", ROOT / "frontend" / "public" / "demo"):
        p = d / name
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:               # pragma: no cover
                pass
    return None


def artifact(name: str):
    """Load a named JSON artifact: MongoDB first, filesystem fallback. Cached."""
    if name in _artifact_cache:
        return _artifact_cache[name]
    data = None
    c = col(ARTIFACTS_COLLECTION)
    if c is not None:
        try:
            doc = c.find_one({"_id": name})
            if doc is not None:
                data = doc.get("data")
        except Exception:                   # pragma: no cover - network hiccup
            data = None
    if data is None:
        data = _fs_artifact(name)
    _artifact_cache[name] = data
    return data


def save_artifact(name: str, data) -> None:
    c = col(ARTIFACTS_COLLECTION)
    if c is None:
        raise RuntimeError("MongoDB not configured")
    c.replace_one({"_id": name}, {"_id": name, "data": data}, upsert=True)
    _artifact_cache.pop(name, None)


# --------------------------------------------------------------------------- #
# v3 artifact store (the cell-centric ml.v3 pipeline JSON in data/processed/v3)
# --------------------------------------------------------------------------- #
# v3 names (pic.json, hotspots.json, forecast_daily.json, dispatch_plan.json,
# online_state.json, evaluation.json, causal.json, sim_rl.json, …) do NOT collide
# with the v1 artifact names, so they can live in the same Mongo `artifacts`
# collection. We prefer a namespaced "v3/<name>" key (future-proof for a tidy
# migration) and fall back to a flat "<name>" key, then the filesystem.
def _fs_v3_artifact(name: str):
    for d in (ROOT / "data" / "processed" / "v3",
              ROOT / "frontend" / "public" / "demo-v3",
              ROOT / "frontend" / "public" / "demo" / "v3"):
        p = d / name
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:               # pragma: no cover
                pass
    return None


def v3_artifact(name: str):
    """Load a named v3 JSON artifact: MongoDB (v3/<name> then <name>) first,
    filesystem (data/processed/v3, demo-v3) fallback. Cached."""
    key = "v3/" + name
    if key in _artifact_cache:
        return _artifact_cache[key]
    data = None
    c = col(ARTIFACTS_COLLECTION)
    if c is not None:
        for _id in (key, name):
            try:
                doc = c.find_one({"_id": _id})
            except Exception:               # pragma: no cover - network hiccup
                doc = None
            if doc is not None and doc.get("data") is not None:
                data = doc["data"]
                break
    if data is None:
        data = _fs_v3_artifact(name)
    _artifact_cache[key] = data
    return data


def save_v3_artifact(name: str, data) -> None:
    c = col(ARTIFACTS_COLLECTION)
    if c is None:
        raise RuntimeError("MongoDB not configured")
    c.replace_one({"_id": "v3/" + name}, {"_id": "v3/" + name, "data": data},
                  upsert=True)
    _artifact_cache.pop("v3/" + name, None)
