"""
ClearLane — operational layer (additive). The live closed loop:
complaint → verify → dispatch → clear.

HARD HONESTY RULE: this layer NEVER modifies the historical ML scores. Every
zone carries three SEPARATE numbers:
  * historical_priority   — the immutable ML output (from map_payload.json)
  * live_adjustment       — a transparent operational boost/cooldown (rules below)
  * operational_priority  — historical + live_adjustment (clamped 0..100)

State persists in MongoDB (collections: complaints, officer_feedback, dispatches,
dispatch_status_history, zone_state) so the app runs on Vercel's read-only
serverless filesystem. The existing read APIs in main.py are untouched; this is a
separate APIRouter.
"""
from __future__ import annotations

import math
import time
from threading import Lock

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import db

router = APIRouter(prefix="/api")

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
def _require_mongo():
    if not db.mongo_enabled():
        raise HTTPException(503, "MongoDB not configured (set MONGODB_URI).")


def zone_index() -> list[dict]:
    """Immutable historical zones (id, name, lat, lon, tier, historical_priority)."""
    global _zone_index
    if _zone_index is None:
        try:
            payload = db.artifact("map_payload.json") or {}
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
def init_db():
    """Create indexes (idempotent). No-op when Mongo is not configured."""
    if not db.mongo_enabled():
        return
    try:
        db.col("complaints").create_index("created_ts")
        db.col("dispatches").create_index("updated_ts")
        db.col("zone_state").create_index("zone_id", unique=True)
    except Exception:                       # pragma: no cover - first-run races
        pass


def _decayed_boost(boost, updated_ts, now):
    if not boost:
        return 0.0
    hours = max(0.0, (now - (updated_ts or now)) / 3600.0)
    return max(0.0, boost - OP_RULES["decay_per_hour"] * hours)


def _bump_zone(zone_id, delta=None, reset=False, state=None, escalate=False,
               add_complaint=False):
    now = time.time()
    c = db.col("zone_state")
    row = c.find_one({"_id": zone_id})
    boost = _decayed_boost(row["boost"], row["updated_ts"], now) if row else 0.0
    if reset:
        boost = 0.0
    elif delta is not None:
        boost = max(0.0, min(OP_RULES["max_adjustment"], boost + delta))
    comp = (row["complaints"] if row else 0) + (1 if add_complaint else 0)
    new_state = state if state is not None else (row["dispatch_state"] if row else None)
    esc = 1 if escalate else (row["escalated"] if row else 0)
    c.replace_one({"_id": zone_id}, {
        "_id": zone_id, "zone_id": zone_id, "boost": boost,
        "dispatch_state": new_state, "escalated": esc,
        "complaints": comp, "updated_ts": now,
    }, upsert=True)


# --------------------------------------------------------------------------- #
# Pydantic input models
# --------------------------------------------------------------------------- #
class ComplaintIn(BaseModel):
    lat: float
    lon: float
    description: str = Field(default="", max_length=500)
    vehicle_type: str = Field(default="", max_length=40)
    vehicle_number: str = Field(default="", max_length=24)


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


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@router.get("/operational/snapshot")
def snapshot():
    now = time.time()
    zi = {z["id"]: z for z in zone_index()}
    if not db.mongo_enabled():
        return ok({"ts": now,
                   "counts": {"active_complaints": 0, "open_dispatches": 0,
                              "live_zones": 0, "escalations": 0},
                   "zones": [], "complaints": [], "dispatches": []})
    states = list(db.col("zone_state").find())
    complaints = list(db.col("complaints").find().sort("created_ts", -1).limit(200))
    dispatches = list(db.col("dispatches").find().sort("updated_ts", -1).limit(200))
    # annotate each complaint/dispatch with its nearest station (from resolved zone)
    for cc in complaints:
        z = zi.get(cc.get("zone_id"))
        cc["station"] = z["station"] if z else None
    for dd in dispatches:
        z = zi.get(dd.get("zone_id"))
        dd["station"] = z["station"] if z else None
        dd["zone_name"] = z["name"] if z else dd.get("zone_id")

    zones = []
    for s in states:
        z = zi.get(s["zone_id"])
        boost = _decayed_boost(s.get("boost"), s.get("updated_ts"), now)
        if boost <= 0 and not s.get("dispatch_state") and not s.get("escalated"):
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
            "dispatch_state": s.get("dispatch_state"),
            "escalated": bool(s.get("escalated")),
            "complaints": s.get("complaints", 0),
        })
    zones.sort(key=lambda x: -x["operational_priority"])
    return ok({
        "ts": now,
        "counts": {
            "active_complaints": sum(1 for x in complaints if x.get("status") != "resolved"),
            "open_dispatches": sum(1 for d in dispatches
                                   if d.get("state") not in ("cleared", "structural_escalation")),
            "live_zones": len(zones),
            "escalations": sum(1 for x in zones if x["escalated"]),
        },
        "zones": zones, "complaints": complaints, "dispatches": dispatches,
    })


@router.get("/operational/changes")
def changes(since: float = 0.0):
    if not db.mongo_enabled():
        return ok({"ts": time.time(), "new_complaints": [], "updated_dispatches": []})
    comp = list(db.col("complaints").find({"created_ts": {"$gt": since}}).sort("created_ts", 1))
    disp = list(db.col("dispatches").find({"updated_ts": {"$gt": since}}).sort("updated_ts", 1))
    return ok({"ts": time.time(), "new_complaints": comp, "updated_dispatches": disp})


@router.post("/complaints")
def post_complaint(body: ComplaintIn):
    _require_mongo()
    if not in_bbox(body.lat, body.lon):
        raise HTTPException(422, "Coordinate outside the Bengaluru bounding box.")
    zone, dist = _nearest_zone(body.lat, body.lon)
    zone_id = zone["id"] if zone else None
    now = time.time()
    plate = body.vehicle_number.upper().strip()
    with _lock:
        cid = db.next_id("complaints")
        db.col("complaints").insert_one({
            "_id": cid, "id": cid, "lat": body.lat, "lon": body.lon,
            "description": body.description, "vehicle_type": body.vehicle_type,
            "vehicle_number": plate, "zone_id": zone_id,
            "distance_m": None if zone is None else round(dist, 1),
            "status": "unverified", "created_ts": now,
        })
        if zone_id:
            _bump_zone(zone_id, delta=OP_RULES["complaint_unverified"], add_complaint=True)
    return ok({"id": cid, "zone_id": zone_id,
               "zone_name": zone["name"] if zone else None,
               "station": zone["station"] if zone else None,
               "vehicle_number": plate or None,
               "assignment": "nearest_historical_zone" if zone else "emerging_operational_point",
               "distance_m": None if zone is None else round(dist, 1), "status": "unverified"})


@router.post("/officer-feedback")
def post_feedback(body: FeedbackIn):
    _require_mongo()
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
    with _lock:
        db.col("officer_feedback").insert_one({
            "_id": db.next_id("officer_feedback"), "zone_id": body.zone_id,
            "dispatch_id": body.dispatch_id, "kind": kind, "note": body.note,
            "created_ts": now,
        })
        _bump_zone(body.zone_id, delta=delta, reset=reset, state=state, escalate=escalate)
        if body.dispatch_id:
            db.col("dispatches").update_one(
                {"_id": body.dispatch_id}, {"$set": {"state": state, "updated_ts": now}})
            db.col("dispatch_status_history").insert_one({
                "_id": db.next_id("dispatch_status_history"),
                "dispatch_id": body.dispatch_id, "state": state, "ts": now})
    return ok({"stored": True, "zone_id": body.zone_id, "kind": kind, "new_state": state})


@router.post("/dispatches")
def post_dispatch(body: DispatchIn):
    _require_mongo()
    if body.state not in DISPATCH_STATES:
        raise HTTPException(422, f"state must be one of {DISPATCH_STATES}")
    now = time.time()
    with _lock:
        did = db.next_id("dispatches")
        db.col("dispatches").insert_one({
            "_id": did, "id": did, "zone_id": body.zone_id,
            "complaint_id": body.complaint_id, "state": body.state,
            "created_ts": now, "updated_ts": now})
        db.col("dispatch_status_history").insert_one({
            "_id": db.next_id("dispatch_status_history"),
            "dispatch_id": did, "state": body.state, "ts": now})
        _bump_zone(body.zone_id, state=body.state)
    return ok({"id": did, "zone_id": body.zone_id, "state": body.state})


@router.patch("/dispatches/{dispatch_id}/status")
def patch_dispatch(dispatch_id: int, body: StatusIn):
    _require_mongo()
    if body.state not in DISPATCH_STATES:
        raise HTTPException(422, f"state must be one of {DISPATCH_STATES}")
    now = time.time()
    with _lock:
        row = db.col("dispatches").find_one({"_id": dispatch_id})
        if not row:
            raise HTTPException(404, "dispatch not found")
        db.col("dispatches").update_one(
            {"_id": dispatch_id}, {"$set": {"state": body.state, "updated_ts": now}})
        db.col("dispatch_status_history").insert_one({
            "_id": db.next_id("dispatch_status_history"),
            "dispatch_id": dispatch_id, "state": body.state, "ts": now})
        # cleared removes the live boost; chronic historical hotspot remains
        if body.state == "cleared":
            _bump_zone(row["zone_id"], reset=True, state="cleared")
        elif body.state == "structural_escalation":
            _bump_zone(row["zone_id"], escalate=True, state="structural_escalation")
        else:
            _bump_zone(row["zone_id"], state=body.state)
    return ok({"id": dispatch_id, "state": body.state})
