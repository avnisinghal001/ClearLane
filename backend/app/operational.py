"""
ClearLane — operational layer (additive). The live closed loop:
complaint → verify → dispatch → clear.

HARD HONESTY RULE: this layer NEVER modifies the historical ML scores. Every
zone carries three SEPARATE numbers:
  * historical_priority   — the immutable ML output (from map_payload.json)
  * live_adjustment       — a transparent operational boost/cooldown (rules below)
  * operational_priority  — historical + live_adjustment (clamped 0..100)

State persists in SQLite (backend/data/clearlane.db), created on startup. The
existing read APIs in main.py are untouched; this is a separate APIRouter.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import time
from pathlib import Path
from threading import Lock

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api")

# --------------------------------------------------------------------------- #
# Paths / artifacts (mirror main.py's resolution so we stay offline-first)
# --------------------------------------------------------------------------- #
ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "backend" / "data" / "clearlane.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

BBOX = {"lat_min": 12.80, "lat_max": 13.29, "lon_min": 77.44, "lon_max": 77.77}

# Transparent operational-priority rules — all live adjustments live HERE.
OP_RULES = {
    "complaint_unverified": 5.0,
    "verified_obstruction": 12.0,
    "needs_towing": 15.0,
    "action_taken": -8.0,
    "false_alarm": -10.0,
    "cleared": None,          # reset live adjustment to 0
    "structural_issue": 0.0,  # no boost; flags escalation instead
    "decay_per_hour": 1.0,    # live adjustment gently decays toward 0
    "max_adjustment": 40.0,
}

DISPATCH_STATES = ["recommended", "assigned", "en_route", "on_site",
                   "action_taken", "cleared", "structural_escalation"]

_lock = Lock()
_zone_index: list[dict] | None = None


# --------------------------------------------------------------------------- #
def _art_dir() -> Path:
    override = os.environ.get("CLEARLANE_ARTIFACTS")
    if override and Path(override).exists():
        return Path(override)
    proc = ROOT / "data" / "processed"
    demo = ROOT / "frontend" / "public" / "demo"
    return proc if (proc / "map_payload.json").exists() else demo


def zone_index() -> list[dict]:
    """Immutable historical zones (id, name, lat, lon, tier, historical_priority)."""
    global _zone_index
    if _zone_index is None:
        try:
            payload = json.loads((_art_dir() / "map_payload.json").read_text())
            _zone_index = [{
                "id": z["id"], "name": z.get("name") or z["id"],
                "lat": z["lat"], "lon": z["lon"], "tier": z["tier"],
                "historical_priority": z["priority"],
                "station": z.get("station"),
            } for z in payload.get("zones", [])]
        except Exception:
            _zone_index = []
    return _zone_index


def _haversine(lat1, lon1, lat2, lon2):
    R = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _nearest_zone(lat, lon, max_m=600):
    best, best_d = None, float("inf")
    for z in zone_index():
        d = _haversine(lat, lon, z["lat"], z["lon"])
        if d < best_d:
            best, best_d = z, d
    if best and best_d <= max_m:
        return best, best_d
    return None, best_d


def in_bbox(lat, lon):
    return (BBOX["lat_min"] <= lat <= BBOX["lat_max"] and
            BBOX["lon_min"] <= lon <= BBOX["lon_max"])


# --------------------------------------------------------------------------- #
def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS complaints(
            id INTEGER PRIMARY KEY AUTOINCREMENT, lat REAL, lon REAL,
            description TEXT, vehicle_type TEXT, zone_id TEXT, distance_m REAL,
            status TEXT DEFAULT 'unverified', created_ts REAL);
        CREATE TABLE IF NOT EXISTS officer_feedback(
            id INTEGER PRIMARY KEY AUTOINCREMENT, zone_id TEXT, dispatch_id INTEGER,
            kind TEXT, note TEXT, created_ts REAL);
        CREATE TABLE IF NOT EXISTS dispatches(
            id INTEGER PRIMARY KEY AUTOINCREMENT, zone_id TEXT, complaint_id INTEGER,
            state TEXT DEFAULT 'recommended', created_ts REAL, updated_ts REAL);
        CREATE TABLE IF NOT EXISTS dispatch_status_history(
            id INTEGER PRIMARY KEY AUTOINCREMENT, dispatch_id INTEGER, state TEXT, ts REAL);
        CREATE TABLE IF NOT EXISTS zone_state(
            zone_id TEXT PRIMARY KEY, boost REAL DEFAULT 0, dispatch_state TEXT,
            escalated INTEGER DEFAULT 0, complaints INTEGER DEFAULT 0,
            updated_ts REAL);
        """)


def _decayed_boost(boost, updated_ts, now):
    if not boost:
        return 0.0
    hours = max(0.0, (now - (updated_ts or now)) / 3600.0)
    return max(0.0, boost - OP_RULES["decay_per_hour"] * hours)


def _bump_zone(c, zone_id, delta=None, reset=False, state=None, escalate=False,
               add_complaint=False):
    now = time.time()
    row = c.execute("SELECT * FROM zone_state WHERE zone_id=?", (zone_id,)).fetchone()
    boost = _decayed_boost(row["boost"], row["updated_ts"], now) if row else 0.0
    if reset:
        boost = 0.0
    elif delta is not None:
        boost = max(0.0, min(OP_RULES["max_adjustment"], boost + delta))
    comp = (row["complaints"] if row else 0) + (1 if add_complaint else 0)
    new_state = state if state is not None else (row["dispatch_state"] if row else None)
    esc = 1 if escalate else (row["escalated"] if row else 0)
    c.execute("""INSERT INTO zone_state(zone_id,boost,dispatch_state,escalated,complaints,updated_ts)
                 VALUES(?,?,?,?,?,?)
                 ON CONFLICT(zone_id) DO UPDATE SET
                   boost=excluded.boost, dispatch_state=excluded.dispatch_state,
                   escalated=excluded.escalated, complaints=excluded.complaints,
                   updated_ts=excluded.updated_ts""",
              (zone_id, boost, new_state, esc, comp, now))


# --------------------------------------------------------------------------- #
# Pydantic input models
# --------------------------------------------------------------------------- #
class ComplaintIn(BaseModel):
    lat: float
    lon: float
    description: str = Field(default="", max_length=500)
    vehicle_type: str = Field(default="", max_length=40)


class FeedbackIn(BaseModel):
    zone_id: str
    kind: str   # verified_obstruction | no_obstruction | needs_towing | action_taken | cleared | false_alarm | structural_issue
    dispatch_id: int | None = None
    note: str = Field(default="", max_length=300)


class DispatchIn(BaseModel):
    zone_id: str
    complaint_id: int | None = None
    state: str = "recommended"


class StatusIn(BaseModel):
    state: str


# ensure tables exist as soon as the module is imported (idempotent)
init_db()


def _safe(obj):
    if isinstance(obj, dict):
        return {k: _safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_safe(v) for v in obj]
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def ok(p):
    return JSONResponse(content=_safe(p))


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@router.get("/operational/snapshot")
def snapshot():
    now = time.time()
    zi = {z["id"]: z for z in zone_index()}
    with _conn() as c:
        states = c.execute("SELECT * FROM zone_state").fetchall()
        complaints = [dict(r) for r in c.execute(
            "SELECT * FROM complaints ORDER BY created_ts DESC LIMIT 200").fetchall()]
        dispatches = [dict(r) for r in c.execute(
            "SELECT * FROM dispatches ORDER BY updated_ts DESC LIMIT 200").fetchall()]

    zones = []
    for s in states:
        z = zi.get(s["zone_id"])
        boost = _decayed_boost(s["boost"], s["updated_ts"], now)
        if boost <= 0 and not s["dispatch_state"] and not s["escalated"]:
            continue
        hist = z["historical_priority"] if z else 0
        zones.append({
            "zone_id": s["zone_id"],
            "name": z["name"] if z else s["zone_id"],
            "lat": z["lat"] if z else None, "lon": z["lon"] if z else None,
            "tier": z["tier"] if z else None,
            "historical_priority": round(hist, 1),
            "live_adjustment": round(boost, 1),
            "operational_priority": round(min(100.0, hist + boost), 1),
            "dispatch_state": s["dispatch_state"],
            "escalated": bool(s["escalated"]),
            "complaints": s["complaints"],
        })
    zones.sort(key=lambda x: -x["operational_priority"])
    return ok({
        "ts": now,
        "counts": {
            "active_complaints": sum(1 for x in complaints if x["status"] != "resolved"),
            "open_dispatches": sum(1 for d in dispatches
                                   if d["state"] not in ("cleared", "structural_escalation")),
            "live_zones": len(zones),
            "escalations": sum(1 for x in zones if x["escalated"]),
        },
        "zones": zones, "complaints": complaints, "dispatches": dispatches,
    })


@router.get("/operational/changes")
def changes(since: float = 0.0):
    with _conn() as c:
        comp = [dict(r) for r in c.execute(
            "SELECT * FROM complaints WHERE created_ts > ? ORDER BY created_ts", (since,)).fetchall()]
        disp = [dict(r) for r in c.execute(
            "SELECT * FROM dispatches WHERE updated_ts > ? ORDER BY updated_ts", (since,)).fetchall()]
    return ok({"ts": time.time(), "new_complaints": comp, "updated_dispatches": disp})


@router.post("/complaints")
def post_complaint(body: ComplaintIn):
    if not in_bbox(body.lat, body.lon):
        raise HTTPException(422, "Coordinate outside the Bengaluru bounding box.")
    zone, dist = _nearest_zone(body.lat, body.lon)
    zone_id = zone["id"] if zone else None
    now = time.time()
    with _lock, _conn() as c:
        cur = c.execute(
            """INSERT INTO complaints(lat,lon,description,vehicle_type,zone_id,distance_m,status,created_ts)
               VALUES(?,?,?,?,?,?,?,?)""",
            (body.lat, body.lon, body.description, body.vehicle_type, zone_id,
             None if zone is None else round(dist, 1), "unverified", now))
        cid = cur.lastrowid
        if zone_id:
            _bump_zone(c, zone_id, delta=OP_RULES["complaint_unverified"], add_complaint=True)
    return ok({"id": cid, "zone_id": zone_id,
               "zone_name": zone["name"] if zone else None,
               "assignment": "nearest_historical_zone" if zone else "emerging_operational_point",
               "distance_m": None if zone is None else round(dist, 1), "status": "unverified"})


@router.post("/officer-feedback")
def post_feedback(body: FeedbackIn):
    now = time.time()
    kind = body.kind
    delta, reset, state, escalate = None, False, None, False
    if kind == "verified_obstruction":
        delta, state = OP_RULES["verified_obstruction"], "on_site"
    elif kind == "needs_towing":
        delta, state = OP_RULES["needs_towing"], "on_site"
    elif kind == "action_taken":
        delta, state = OP_RULES["action_taken"], "action_taken"
    elif kind == "cleared":
        reset, state = True, "cleared"
    elif kind == "false_alarm":
        delta, state = OP_RULES["false_alarm"], "cleared"
    elif kind == "structural_issue":
        escalate, state = True, "structural_escalation"
    elif kind in ("no_obstruction", "no_obstruction_found"):
        delta, state = OP_RULES["false_alarm"], "cleared"
    else:
        raise HTTPException(422, f"Unknown feedback kind '{kind}'.")
    with _lock, _conn() as c:
        c.execute("""INSERT INTO officer_feedback(zone_id,dispatch_id,kind,note,created_ts)
                     VALUES(?,?,?,?,?)""", (body.zone_id, body.dispatch_id, kind, body.note, now))
        _bump_zone(c, body.zone_id, delta=delta, reset=reset, state=state, escalate=escalate)
        if body.dispatch_id:
            c.execute("UPDATE dispatches SET state=?, updated_ts=? WHERE id=?",
                      (state, now, body.dispatch_id))
            c.execute("INSERT INTO dispatch_status_history(dispatch_id,state,ts) VALUES(?,?,?)",
                      (body.dispatch_id, state, now))
    return ok({"stored": True, "zone_id": body.zone_id, "kind": kind, "new_state": state})


@router.post("/dispatches")
def post_dispatch(body: DispatchIn):
    if body.state not in DISPATCH_STATES:
        raise HTTPException(422, f"state must be one of {DISPATCH_STATES}")
    now = time.time()
    with _lock, _conn() as c:
        cur = c.execute("""INSERT INTO dispatches(zone_id,complaint_id,state,created_ts,updated_ts)
                           VALUES(?,?,?,?,?)""",
                        (body.zone_id, body.complaint_id, body.state, now, now))
        did = cur.lastrowid
        c.execute("INSERT INTO dispatch_status_history(dispatch_id,state,ts) VALUES(?,?,?)",
                  (did, body.state, now))
        _bump_zone(c, body.zone_id, state=body.state)
    return ok({"id": did, "zone_id": body.zone_id, "state": body.state})


@router.patch("/dispatches/{dispatch_id}/status")
def patch_dispatch(dispatch_id: int, body: StatusIn):
    if body.state not in DISPATCH_STATES:
        raise HTTPException(422, f"state must be one of {DISPATCH_STATES}")
    now = time.time()
    with _lock, _conn() as c:
        row = c.execute("SELECT * FROM dispatches WHERE id=?", (dispatch_id,)).fetchone()
        if not row:
            raise HTTPException(404, "dispatch not found")
        c.execute("UPDATE dispatches SET state=?, updated_ts=? WHERE id=?",
                  (body.state, now, dispatch_id))
        c.execute("INSERT INTO dispatch_status_history(dispatch_id,state,ts) VALUES(?,?,?)",
                  (dispatch_id, body.state, now))
        # cleared removes the live boost; chronic historical hotspot remains
        if body.state == "cleared":
            _bump_zone(c, row["zone_id"], reset=True, state="cleared")
        elif body.state == "structural_escalation":
            _bump_zone(c, row["zone_id"], escalate=True, state="structural_escalation")
        else:
            _bump_zone(c, row["zone_id"], state=body.state)
    return ok({"id": dispatch_id, "state": body.state})
