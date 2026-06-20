"""
ClearLane — Force Command layer (RBAC + station roster + troop simulation).

This is a clearly-labelled DEPLOYMENT / OPERATIONS layer. Like operational.py it
NEVER touches the historical ML scores. It adds:

  * RBAC auth (token sessions in MongoDB):
      - Government super-admin:  username "govt" / password "govt"  -> sees all
      - Per-station command:     username == password == station slug  (e.g.
        "HAL Old Airport" -> "hal-old-airport") -> sees ONLY its own area
  * A MongoDB store for managing area-level forces:
      - fz_stations  (police stations; govt can add / remove)
      - fz_officers  (ranked officers per station; add / remove / re-shift)
  * Deterministic seeding from the real station list (stations.json) so every
    station boots with a realistic ranked roster across three shifts.

State persists in MongoDB so the app runs on Vercel's read-only serverless
filesystem. The live troop-tracking *movement* simulation runs client-side
(frontend/src/lib/force.js) for smooth animation and full offline support; this
backend is the source of truth for auth + roster persistence. Honesty: officer
positions are a SIMULATION for deployment planning, never a claim about measured
traffic.
"""
from __future__ import annotations

import math
import re
import secrets
import time
from threading import Lock

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import db

router = APIRouter(prefix="/api")

_lock = Lock()

# Indian-police station hierarchy (high -> low). SHO is the station Inspector.
RANKS = ["Inspector", "Police Sub-Inspector", "Assistant Sub-Inspector",
         "Head Constable", "Constable"]
# Three rotating shifts (IST hour ranges). "C" wraps past midnight.
SHIFTS = {
    "A": {"label": "Morning", "start": 6, "end": 14},
    "B": {"label": "Evening", "start": 14, "end": 22},
    "C": {"label": "Night", "start": 22, "end": 6},
}
_NAMES_FIRST = ["Arjun", "Vikram", "Suresh", "Ramesh", "Manjunath", "Kiran",
                "Prakash", "Naveen", "Ravi", "Anil", "Deepak", "Girish",
                "Harish", "Lokesh", "Mahesh", "Nandish", "Praveen", "Rakesh",
                "Santosh", "Umesh", "Yogesh", "Basava", "Chetan", "Dinesh",
                "Ganesh", "Hemanth", "Imran", "Jagdish", "Kishore", "Lavanya",
                "Meena", "Nagaraj", "Pooja", "Roopa", "Shilpa", "Tejaswini"]
_NAMES_LAST = ["Gowda", "Reddy", "Naik", "Rao", "Shetty", "Kumar", "Murthy",
               "Hegde", "Patil", "Iyer", "Nair", "Babu", "Das", "Singh",
               "Prasad", "Bhat", "Acharya", "Desai", "Kulkarni", "Pai"]


# --------------------------------------------------------------------------- #
def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or "station"


def _load_stations_seed() -> list[dict]:
    return db.artifact("stations.json") or []


def _rng(seed: int):
    """Tiny deterministic LCG so seeding is reproducible without numpy."""
    state = {"s": (seed * 2654435761) & 0xFFFFFFFF}

    def nxt(n):  # int in [0, n)
        state["s"] = (1103515245 * state["s"] + 12345) & 0x7FFFFFFF
        return state["s"] % n
    return nxt


def _require_mongo():
    if not db.mongo_enabled():
        raise HTTPException(503, "MongoDB not configured (set MONGODB_URI).")


_INIT_DONE = False


def init_db():
    """Create indexes + seed rosters (idempotent). No-op without Mongo."""
    if not db.mongo_enabled():
        return
    try:
        db.col("fz_officers").create_index("station_slug")
        db.col("fz_sessions").create_index("token", unique=True)
    except Exception:                       # pragma: no cover
        pass
    _seed_if_empty()


def _ensure_init():
    """Lazy, once-per-process bootstrap. Vercel's serverless runtime does not run
    ASGI lifespan/startup events reliably, so every entry point calls this instead
    of depending on @app.on_event('startup')."""
    global _INIT_DONE
    if _INIT_DONE or not db.mongo_enabled():
        return
    init_db()
    _INIT_DONE = True


def _seed_station_officers(slug, n_zones):
    """Create a realistic ranked roster, round-robin across the 3 shifts."""
    size = max(6, min(18, round(n_zones * 0.35) + 5))
    rng = _rng(sum(ord(ch) for ch in slug) + size)
    # rank counts: 1 Inspector, up to 2 SI, up to 2 ASI, rest HC / Constable
    plan = ["Inspector"]
    plan += ["Police Sub-Inspector"] * min(2, max(1, size // 6))
    plan += ["Assistant Sub-Inspector"] * min(2, max(1, size // 6))
    while len(plan) < size:
        plan.append("Head Constable" if rng(10) < 4 else "Constable")
    now = time.time()
    shifts = ["A", "B", "C"]
    rows = []
    for i, rank in enumerate(plan):
        fn = _NAMES_FIRST[rng(len(_NAMES_FIRST))]
        ln = _NAMES_LAST[rng(len(_NAMES_LAST))]
        shift = shifts[i % 3]
        badge = f"{slug[:3].upper()}-{1000 + i}"
        oid = db.next_id("fz_officers")
        rows.append({
            "_id": oid, "id": oid, "station_slug": slug,
            "name": f"{fn} {ln}", "badge": badge, "rank": rank,
            "shift": shift, "status": "available", "created_ts": now})
    if rows:
        db.col("fz_officers").insert_many(rows)


def _seed_if_empty():
    from pymongo.errors import DuplicateKeyError
    with _lock:
        if db.col("fz_stations").estimated_document_count():
            return
        now = time.time()
        for s in _load_stations_seed():
            name = s.get("station") or "Station"
            if name == "No Police Station":
                continue
            slug = slugify(name)
            if db.col("fz_stations").find_one({"_id": slug}):
                continue
            try:
                db.col("fz_stations").insert_one({
                    "_id": slug, "slug": slug, "name": name,
                    "lat": s.get("lat"), "lon": s.get("lon"),
                    "n_zones": int(s.get("n_zones") or 0),
                    "seeded": 1, "active": 1, "created_ts": now})
            except DuplicateKeyError:        # concurrent cold start already seeded
                continue
            _seed_station_officers(slug, int(s.get("n_zones") or 0))


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
class LoginIn(BaseModel):
    username: str = Field(max_length=80)
    password: str = Field(max_length=80)


def _session(token: str | None):
    if not token or not db.mongo_enabled():
        return None
    return db.col("fz_sessions").find_one({"token": token})


def _auth(authorization: str | None):
    """Resolve the bearer token -> session, or raise 401."""
    _ensure_init()
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    sess = _session(token)
    if not sess:
        raise HTTPException(401, "Not authenticated.")
    return sess


def _require_scope(sess: dict, slug: str | None):
    """Govt may touch any station; a station may touch only its own."""
    if sess["role"] == "govt":
        return
    if not slug or slug != sess["scope"]:
        raise HTTPException(403, "Out of scope for this account.")


@router.post("/auth/login")
def login(body: LoginIn):
    _require_mongo()
    _ensure_init()
    user = (body.username or "").strip().lower()
    pw = (body.password or "").strip().lower()
    role, scope, name = None, None, None
    if user == "govt" and pw == "govt":
        role, scope, name = "govt", "all", "Government Command"
    else:
        r = db.col("fz_stations").find_one({"slug": user, "active": 1})
        # slug is BOTH username and password (demo RBAC, as specified)
        if r and pw == user:
            role, scope, name = "station", r["slug"], r["name"]
    if not role:
        raise HTTPException(401, "Invalid credentials.")
    token = secrets.token_urlsafe(24)
    db.col("fz_sessions").insert_one({
        "token": token, "role": role, "scope": scope, "name": name,
        "created_ts": time.time()})
    return ok({"token": token, "role": role, "scope": scope, "name": name})


@router.post("/auth/logout")
def logout(authorization: str | None = Header(default=None)):
    if authorization and authorization.lower().startswith("bearer ") and db.mongo_enabled():
        tok = authorization[7:].strip()
        db.col("fz_sessions").delete_one({"token": tok})
    return ok({"ok": True})


@router.get("/auth/me")
def me(authorization: str | None = Header(default=None)):
    sess = _auth(authorization)
    return ok({"role": sess["role"], "scope": sess["scope"], "name": sess["name"]})


# --------------------------------------------------------------------------- #
# Helpers to assemble roster / station summaries
# --------------------------------------------------------------------------- #
def _officer_rows(slug):
    return list(db.col("fz_officers").find({"station_slug": slug}).sort("_id", 1))


def _station_dict(r):
    n_off = db.col("fz_officers").count_documents({"station_slug": r["slug"]})
    return {"slug": r["slug"], "name": r["name"], "lat": r["lat"], "lon": r["lon"],
            "n_zones": r.get("n_zones", 0), "officers": n_off,
            "active": bool(r.get("active", 1))}


# --------------------------------------------------------------------------- #
# Government endpoints (require govt role)
# --------------------------------------------------------------------------- #
class StationIn(BaseModel):
    name: str = Field(max_length=120)
    lat: float
    lon: float


@router.get("/govt/stations")
def govt_stations(authorization: str | None = Header(default=None)):
    sess = _auth(authorization)
    if sess["role"] != "govt":
        raise HTTPException(403, "Government access only.")
    rows = list(db.col("fz_stations").find().sort("name", 1))
    out = [_station_dict(r) for r in rows]
    total_off = db.col("fz_officers").estimated_document_count()
    return ok({"stations": out,
               "totals": {"stations": len(out), "officers": total_off}})


@router.post("/govt/stations")
def govt_add_station(body: StationIn, authorization: str | None = Header(default=None)):
    sess = _auth(authorization)
    if sess["role"] != "govt":
        raise HTTPException(403, "Government access only.")
    slug = slugify(body.name)
    now = time.time()
    with _lock:
        if db.col("fz_stations").find_one({"_id": slug}):
            raise HTTPException(409, f"Station '{slug}' already exists.")
        db.col("fz_stations").insert_one({
            "_id": slug, "slug": slug, "name": body.name,
            "lat": body.lat, "lon": body.lon, "n_zones": 0,
            "seeded": 1, "active": 1, "created_ts": now})
        _seed_station_officers(slug, 12)
    return ok({"slug": slug, "name": body.name,
               "login": {"username": slug, "password": slug}})


@router.delete("/govt/stations/{slug}")
def govt_remove_station(slug: str, authorization: str | None = Header(default=None)):
    sess = _auth(authorization)
    if sess["role"] != "govt":
        raise HTTPException(403, "Government access only.")
    with _lock:
        db.col("fz_officers").delete_many({"station_slug": slug})
        db.col("fz_sessions").delete_many({"scope": slug})
        res = db.col("fz_stations").delete_one({"_id": slug})
    if res.deleted_count == 0:
        raise HTTPException(404, "Station not found.")
    return ok({"removed": slug})


# --------------------------------------------------------------------------- #
# Roster endpoints (govt or the owning station)
# --------------------------------------------------------------------------- #
class OfficerIn(BaseModel):
    station_slug: str = Field(max_length=80)
    name: str = Field(max_length=80)
    rank: str = Field(default="Constable", max_length=60)
    shift: str = Field(default="A", max_length=2)


class OfficerPatch(BaseModel):
    rank: str | None = Field(default=None, max_length=60)
    shift: str | None = Field(default=None, max_length=2)
    status: str | None = Field(default=None, max_length=20)


@router.get("/force/roster")
def force_roster(station: str, authorization: str | None = Header(default=None)):
    sess = _auth(authorization)
    _require_scope(sess, station)
    st = db.col("fz_stations").find_one({"slug": station})
    if not st:
        raise HTTPException(404, "Station not found.")
    officers = _officer_rows(station)
    sd = _station_dict(st)
    return ok({"station": sd, "officers": officers, "ranks": RANKS, "shifts": SHIFTS})


@router.post("/force/officers")
def force_add_officer(body: OfficerIn, authorization: str | None = Header(default=None)):
    sess = _auth(authorization)
    _require_scope(sess, body.station_slug)
    rank = body.rank if body.rank in RANKS else "Constable"
    shift = body.shift if body.shift in SHIFTS else "A"
    now = time.time()
    with _lock:
        if not db.col("fz_stations").find_one({"slug": body.station_slug}):
            raise HTTPException(404, "Station not found.")
        n = db.col("fz_officers").count_documents({"station_slug": body.station_slug})
        badge = f"{body.station_slug[:3].upper()}-{1000 + n}"
        oid = db.next_id("fz_officers")
        db.col("fz_officers").insert_one({
            "_id": oid, "id": oid, "station_slug": body.station_slug, "name": body.name,
            "badge": badge, "rank": rank, "shift": shift,
            "status": "available", "created_ts": now})
    return ok({"id": oid, "badge": badge, "name": body.name,
               "rank": rank, "shift": shift})


@router.patch("/force/officers/{oid}")
def force_patch_officer(oid: int, body: OfficerPatch,
                        authorization: str | None = Header(default=None)):
    sess = _auth(authorization)
    with _lock:
        row = db.col("fz_officers").find_one({"_id": oid})
        if not row:
            raise HTTPException(404, "Officer not found.")
        _require_scope(sess, row["station_slug"])
        rank = body.rank if (body.rank in RANKS) else row["rank"]
        shift = body.shift if (body.shift in SHIFTS) else row["shift"]
        status = body.status or row["status"]
        db.col("fz_officers").update_one(
            {"_id": oid}, {"$set": {"rank": rank, "shift": shift, "status": status}})
    return ok({"id": oid, "rank": rank, "shift": shift, "status": status})


@router.delete("/force/officers/{oid}")
def force_remove_officer(oid: int, authorization: str | None = Header(default=None)):
    sess = _auth(authorization)
    with _lock:
        row = db.col("fz_officers").find_one({"_id": oid})
        if not row:
            raise HTTPException(404, "Officer not found.")
        _require_scope(sess, row["station_slug"])
        db.col("fz_officers").delete_one({"_id": oid})
    return ok({"removed": oid})


# --------------------------------------------------------------------------- #
def _safe(obj):
    if isinstance(obj, dict):
        return {k: _safe(v) for k, v in obj.items() if k != "_id"}
    if isinstance(obj, list):
        return [_safe(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def ok(p):
    return JSONResponse(content=_safe(p))
