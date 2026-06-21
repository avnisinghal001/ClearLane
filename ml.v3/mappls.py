"""
ClearLane v3 — Mappls REST adapter (OAuth2 + two-tier cache).

Auth (per-product, verified live for this account):
  * Nearby/geocode  -> atlas.mappls.com with an OAuth2 BEARER token minted from
                       client_id + client_secret (cached in-process, refreshed
                       before expiry). The static key alone 401s on atlas.
  * Distance-Time Matrix (drive time) -> the LEGACY apis.mappls.com/advancedmaps
                       path form with the REST key IN THE PATH. distance_matrix =
                       free-flow, distance_matrix_eta = TYPICAL-traffic ETA (Mappls'
                       historical patterns, not real-time). The OAuth route.mappls.com
                       hosts 401 "Token was not recognised" here.
Predictive-ETA / live-traffic / isochrone / trip-opt live on route.mappls.com (or the
distance_matrix_traffic resource), which this account cannot reach -> those features
degrade to the offline proxy (never fabricated).

Caching is delegated to the `cache` package (ml.v3/cache):
  * STATIC kinds (nearby/geocode/snap/...) -> local JSON + MongoDB (durable),
  * LIVE kinds (eta/isochrone/...)         -> MongoDB only, with a TTL.
Offline / no-key / error -> callers receive neutral sentinels; the pipeline still
runs from whatever is already cached.

HONESTY: Mappls supplies geographic CONTEXT (POIs, road snap, drive time) and a
live TRAVEL-TIME ratio — never a measurement of congestion from our ticket data.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config as C   # noqa: E402
import utils as U    # noqa: E402
from cache import cache as CACHE   # noqa: E402  (two-tier local-JSON + MongoDB cache)

_TOKEN: dict = {"value": None, "exp": 0.0}      # cached OAuth bearer token


def _env(*names):
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return None


def static_key() -> str | None:
    """SDK/browser Map-widget key — NOT valid for REST calls (kept for completeness)."""
    return _env(C.MAPPLS_STATIC_KEY_ENV, C.MAPPLS_API_KEY_ENV)


def rest_key() -> str | None:
    """REST key for the advancedmaps PATH form (distance-matrix, rev_geocode). Falls
    back to the old combined key name so a half-migrated .env still works."""
    return _env(C.MAPPLS_REST_KEY_ENV, C.MAPPLS_API_KEY_ENV)


def _client_creds():
    # Tolerant of the common MAPPLE_/MAPPLS_ spelling slip.
    cid = _env(C.MAPPLS_CLIENT_ID_ENV, "MAPPLE_CLIENT_ID")
    sec = _env(C.MAPPLS_CLIENT_SECRET_ENV, "MAPPLE_CLIENT_SECRET")
    return (cid, sec) if (cid and sec) else (None, None)


def _oauth_token() -> str | None:
    """Mint (and cache) an OAuth2 bearer token from client_id + client_secret.

    Mappls REST APIs (search/route) require this; the static SDK key 401s. The
    token is valid ~24h; we cache it in-process and refresh ~60s before expiry.
    """
    cid, sec = _client_creds()
    if not (cid and sec):
        return None
    import time
    now = time.time()
    if _TOKEN["value"] and now < _TOKEN["exp"] - 60:
        return _TOKEN["value"]
    try:
        q = urllib.parse.urlencode({"grant_type": "client_credentials",
                                    "client_id": cid, "client_secret": sec})
        req = urllib.request.Request(f"{C.MAPPLS_TOKEN_URL}?{q}", data=b"",
                                     method="POST",
                                     headers={"User-Agent": "ClearLane/3.0"})
        with urllib.request.urlopen(req, timeout=C.MAPPLS_TIMEOUT_S) as r:
            d = json.loads(r.read().decode("utf-8"))
        tok = d.get("access_token")
        if tok:
            _TOKEN["value"] = tok
            _TOKEN["exp"] = now + float(d.get("expires_in", 3600))
        return tok
    except Exception:
        return None


def access_token() -> str | None:
    """The token to send as `access_token`: OAuth bearer if creds exist, else the
    static key (works only for accounts where the REST key is provisioned)."""
    return _oauth_token() or static_key()


# Back-compat alias.
def api_key() -> str | None:
    return access_token()


def available() -> bool:
    return bool(C.MAPPLS_ENABLED and access_token())


def predictive_available() -> bool:
    """Mappls' own per-hour Predictive-ETA product (route.mappls.com routev2/dm).
    NOT provisioned for this account -> stage 07 stays honest (api_unavailable)."""
    return bool(C.MAPPLS_PREDICTIVE_ENABLED and available())


def _round(v: float) -> float:
    return round(float(v), C.MAPPLS_COORD_DECIMALS)


def flush():
    """Persist buffered cache writes (local JSON + MongoDB). Call at stage end."""
    CACHE.flush()


def _http_get_json(url: str):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ClearLane/3.0"})
        with urllib.request.urlopen(req, timeout=C.MAPPLS_TIMEOUT_S) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


# Circuit breakers: after a few failures (product not enabled / quota), stop trying
# that host for the rest of the process and fall back to offline proxies/sentinels.
#   _ROUTE -> live ETA / distance-matrix calls.   _ATLAS -> Nearby/geocode.
_ROUTE = {"fails": 0, "down": False}
_ATLAS = {"fails": 0, "down": False}


def _breaker_get_json(state: dict, limit: int, url: str):
    if state["down"]:
        return None
    data = _http_get_json(url)
    if data is None:
        state["fails"] += 1
        if state["fails"] >= limit:
            state["down"] = True
    else:
        state["fails"] = 0
    return data


def route_down() -> bool:
    return _ROUTE["down"]


def atlas_down() -> bool:
    return _ATLAS["down"]


def _route_get_json(url: str):
    return _breaker_get_json(_ROUTE, C.MAPPLS_ROUTE_FAIL_LIMIT, url)


def _atlas_get_json(url: str):
    return _breaker_get_json(_ATLAS, C.MAPPLS_ATLAS_FAIL_LIMIT, url)


# --------------------------------------------------------------------------- #
# Nearby POI -> (nearest distance m, count within radius). Offline -> sentinel.
# (Readme-18 / readme-11)
# --------------------------------------------------------------------------- #
def nearby_poi(lat: float, lon: float, keyword: str, radius: int):
    """Nearest POI distance (m) + count within radius via Mappls Nearby (atlas host).

    Host is atlas.mappls.com/api/places/nearby/json — the OAuth-token host for this
    account (search.mappls.com returns 401 "Token was not recognised"). The Nearby
    response gives `distance` (metres) per suggestion directly; we take the minimum.
    """
    lat, lon = _round(lat), _round(lon)
    key = f"{lat},{lon}|{keyword}|{radius}"

    def url():
        q = urllib.parse.urlencode({"keywords": keyword, "refLocation": f"{lat},{lon}",
                                    "radius": radius, "region": "IND",
                                    "access_token": access_token()})
        return f"https://atlas.mappls.com/api/places/nearby/json?{q}"

    def fetch():
        return _atlas_get_json(url()) if available() else None

    data = CACHE.get_or_fetch("nearby", key, fetch, live=False)
    locs = (data or {}).get("suggestedLocations") if isinstance(data, dict) else None
    if not locs:
        return (C.MAPPLS_POI_FAR_M, 0)
    dmin, cnt = C.MAPPLS_POI_FAR_M, 0
    for p in locs:
        d = p.get("distance")                       # Mappls network distance (m)
        if d is None:                               # fallback to haversine if coords given
            try:
                d = U.haversine_m(lat, lon, float(p["latitude"]), float(p["longitude"]))
            except Exception:
                continue
        dmin = min(dmin, float(d)); cnt += 1
    return (round(float(dmin), 1), int(cnt))


# --------------------------------------------------------------------------- #
# advancedmaps REST helper: {BASE}/<REST_KEY>/<path>?<params>. The REST key goes in
# the PATH (this account's only working route product). None if no REST key.
# --------------------------------------------------------------------------- #
def _advancedmaps_url(path: str, **params) -> str | None:
    rk = rest_key()
    if not rk:
        return None
    base = f"{C.MAPPLS_ADVANCEDMAPS_BASE}/{rk}/{path}"
    return f"{base}?{urllib.parse.urlencode(params)}" if params else base


# --------------------------------------------------------------------------- #
# A->B drive time (Phase 2) via the Mappls Distance-Time Matrix (readme-10), legacy
# advancedmaps path form + REST key. speed -> resource:
#   "traffic" -> distance_matrix_eta (Mappls TYPICAL-traffic ETA, historical),
#   "optimal" -> distance_matrix     (free-flow, no traffic).
# Returns seconds, or None offline / unsupported (predictive needs the route.* host,
# which 401s for this account). Never derived from ticket data.
# --------------------------------------------------------------------------- #
_DM_RESOURCE = {"traffic": C.MAPPLS_DM_RESOURCE_ETA, "eta": C.MAPPLS_DM_RESOURCE_ETA,
                "typical": C.MAPPLS_DM_RESOURCE_ETA, "optimal": C.MAPPLS_DM_RESOURCE_FREE,
                "free": C.MAPPLS_DM_RESOURCE_FREE, "shortest": C.MAPPLS_DM_RESOURCE_FREE}


def _dm_seconds(data):
    """Source->destination seconds from a 1-source distance-matrix response. Row 0 is
    [src->src=0, src->dst], so the cross term is the LAST column (a 1x1 reply is just
    [[src->dst]]); the [0][0] diagonal is 0 and must not be used."""
    try:
        row = data["results"]["durations"][0]
        v = float(row[-1])
    except Exception:
        return None
    return v if v > 0 else None


def eta_seconds(src_lat, src_lon, dst_lat, dst_lon, speed="traffic", date_time=None):
    resource = _DM_RESOURCE.get(speed)
    if resource is None or date_time:    # predictive / per-hour -> not provisioned
        return None                      # (route.mappls.com 401s for this account)
    if not (C.MAPPLS_ENABLED and rest_key()):
        return None
    a, b = (_round(src_lat), _round(src_lon)), (_round(dst_lat), _round(dst_lon))
    key = f"{resource}|{a[0]},{a[1]}|{b[0]},{b[1]}"

    def fetch():
        url = _advancedmaps_url(f"{resource}/driving/{a[1]},{a[0]};{b[1]},{b[0]}",
                               rtype=C.MAPPLS_DM_RTYPE, region=C.MAPPLS_DM_REGION)
        return _route_get_json(url) if url else None

    # LIVE tier: cached in MongoDB only, with a TTL (typical curve still varies by run).
    data = CACHE.get_or_fetch("eta", key, fetch, live=True, ttl=C.CACHE_LIVE_TTL_S)
    return _dm_seconds(data)


def congestion_severity(src_lat, src_lon, dst_lat, dst_lon):
    """Mappls TYPICAL-traffic congestion ratio in [0,1] for an A->B segment (or None).

        severity = clip(1 - free_flow / typical_eta, 0, 1)
          free_flow   = distance_matrix      (no-traffic duration)
          typical_eta = distance_matrix_eta  (Mappls historical typical-traffic ETA)

    A Mappls-MEASURED typical ratio — NOT real-time, NOT predictive, NEVER from the
    ticket data. Label its source "mappls_typical" wherever it surfaces.
    """
    free = eta_seconds(src_lat, src_lon, dst_lat, dst_lon, speed="optimal")
    eta = eta_seconds(src_lat, src_lon, dst_lat, dst_lon, speed="traffic")
    if not free or not eta or eta <= 0:
        return None
    return max(0.0, min(1.0, 1.0 - free / eta))
