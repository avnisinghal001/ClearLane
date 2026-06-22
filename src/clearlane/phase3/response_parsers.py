"""Pure parsers for Mappls response bodies.

These functions never perform I/O. They classify provider-level errors (which
Mappls sometimes returns with HTTP 200) and extract typed numeric results. A
parser raises ProviderError for an authentication/quota/denied body so callers
treat it as failure regardless of HTTP status.

Verified against real sanitized samples:
  Route ADV/ETA:  {"routes":[{"duration","distance","geometry"}],"code":"Ok","waypoints":[...]}
  Matrix:         {"results":{"distances":[[...]],"durations":[[...]],"code":"Ok"},"responseCode":200}
  Snap:           {"results":{"snappedPoints":[{"distance","location":[lng,lat],"waypoint_index"}]}}
  Reverse geocode:{"responseCode":200,"results":[{"street","subLocality","locality","formatted_address"}]}
  Denied (HTTP200):{"msg":"Api access denied ...","error":"Api Access Denied"}
  Invalid token:  {"msg":"Token was not recognised","error":"Invalid Token"}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

# provider_status values
PROVIDER_OK = "OK"
ACCESS_DENIED = "ACCESS_DENIED"
INVALID_TOKEN = "INVALID_TOKEN"
UNAUTHORIZED = "UNAUTHORIZED"
RATE_LIMITED = "RATE_LIMITED"
INVALID_RESPONSE = "INVALID_RESPONSE"
ROUTE_NOT_FOUND = "ROUTE_NOT_FOUND"
EMPTY_RESULT = "EMPTY_RESULT"


class ProviderError(RuntimeError):
    def __init__(self, provider_status: str, message: str):
        super().__init__(f"{provider_status}: {message}")
        self.provider_status = provider_status
        self.message = message


def classify_error(body: Any, http_status: int | None = None) -> Optional[str]:
    """Return a provider_status if the body/status indicates failure, else None."""
    if http_status is not None:
        if http_status == 401:
            return UNAUTHORIZED
        if http_status == 403:
            return ACCESS_DENIED
        if http_status == 429:
            return RATE_LIMITED

    if isinstance(body, str):
        low = body.lower()
        if "invalid token" in low or "token was not recognised" in low or "token was not recognized" in low:
            return INVALID_TOKEN
        if "access denied" in low:
            return ACCESS_DENIED
        return None

    if not isinstance(body, dict):
        return None

    err = str(body.get("error", "")).lower()
    msg = str(body.get("msg", "")).lower()
    blob = err + " " + msg
    if "invalid token" in blob or "not recognis" in blob or "not recogniz" in blob:
        return INVALID_TOKEN
    if "access denied" in blob:
        return ACCESS_DENIED
    if "unauthor" in blob:
        return UNAUTHORIZED
    if "rate limit" in blob or "too many requests" in blob:
        return RATE_LIMITED
    rc = body.get("responseCode")
    if rc in (401,):
        return UNAUTHORIZED
    if rc in (403,):
        return ACCESS_DENIED
    if rc in (429,):
        return RATE_LIMITED
    return None


def _raise_if_error(body: Any, http_status: int | None = None) -> None:
    status = classify_error(body, http_status)
    if status is not None:
        msg = ""
        if isinstance(body, dict):
            msg = str(body.get("msg") or body.get("error") or "")
        raise ProviderError(status, msg)


@dataclass
class RouteResult:
    distance_m: float
    duration_s: float
    geometry: Optional[str]
    road_name: str
    provider_status: str = PROVIDER_OK
    waypoints: list = field(default_factory=list)


def parse_route(body: Any, http_status: int | None = None) -> RouteResult:
    """Parse Route ADV or Route ETA. Same response shape for both."""
    _raise_if_error(body, http_status)
    if not isinstance(body, dict):
        raise ProviderError(INVALID_RESPONSE, "non-object route body")
    code = str(body.get("code", "")).lower()
    routes = body.get("routes") or []
    if code and code not in ("ok", "okay"):
        raise ProviderError(ROUTE_NOT_FOUND, f"route code={code}")
    if not routes:
        raise ProviderError(ROUTE_NOT_FOUND, "no routes returned")
    r0 = routes[0]
    dist = r0.get("distance")
    dur = r0.get("duration")
    if dist is None:
        raise ProviderError(INVALID_RESPONSE, "route missing distance")
    if dur is None:
        raise ProviderError(INVALID_RESPONSE, "route missing duration")
    waypoints = body.get("waypoints") or []
    road_name = ""
    for wp in waypoints:
        if wp.get("name"):
            road_name = str(wp["name"])
            break
    if not road_name:
        legs = r0.get("legs") or []
        if legs and legs[0].get("summary"):
            road_name = str(legs[0]["summary"])
    return RouteResult(
        distance_m=float(dist),
        duration_s=float(dur),
        geometry=r0.get("geometry"),
        road_name=road_name,
        waypoints=waypoints,
    )


@dataclass
class MatrixResult:
    distances: list[list[Optional[float]]]
    durations: list[list[Optional[float]]]
    rows: int
    cols: int
    provider_status: str = PROVIDER_OK


def parse_matrix(body: Any, http_status: int | None = None) -> MatrixResult:
    """Parse Distance Matrix (normal or ETA). Same shape for both."""
    _raise_if_error(body, http_status)
    if not isinstance(body, dict):
        raise ProviderError(INVALID_RESPONSE, "non-object matrix body")
    results_raw = body.get("results")
    if isinstance(results_raw, list):
        results = results_raw[0] if results_raw else None
    else:
        results = results_raw
    if not isinstance(results, dict):
        raise ProviderError(INVALID_RESPONSE, "matrix missing results")
    code = str(results.get("code", "")).lower()
    if code and code not in ("ok", "okay"):
        raise ProviderError(ROUTE_NOT_FOUND, f"matrix code={code}")
    distances = results.get("distances")
    durations = results.get("durations")
    if distances is None:
        raise ProviderError(INVALID_RESPONSE, "matrix missing distances")
    if durations is None:
        raise ProviderError(INVALID_RESPONSE, "matrix missing durations")
    if not distances or not distances[0]:
        raise ProviderError(EMPTY_RESULT, "empty matrix")
    return MatrixResult(
        distances=distances,
        durations=durations,
        rows=len(durations),
        cols=len(durations[0]) if durations else 0,
    )


@dataclass
class SnapPoint:
    lat: float
    lng: float
    snap_distance_m: float
    waypoint_index: int


def parse_snap(body: Any, http_status: int | None = None) -> list[SnapPoint]:
    _raise_if_error(body, http_status)
    if not isinstance(body, dict):
        raise ProviderError(INVALID_RESPONSE, "non-object snap body")
    results = body.get("results") or {}
    pts = results.get("snappedPoints") or body.get("snappedPoints") or []
    out: list[SnapPoint] = []
    for p in pts:
        loc = p.get("location") or []
        if len(loc) != 2:
            continue
        # Mappls snap returns [lng, lat]
        out.append(
            SnapPoint(
                lat=float(loc[1]),
                lng=float(loc[0]),
                snap_distance_m=float(p.get("distance", 0.0)),
                waypoint_index=int(p.get("waypoint_index", len(out))),
            )
        )
    if not out:
        raise ProviderError(EMPTY_RESULT, "no snapped points")
    return out


@dataclass
class ReverseGeocodeResult:
    locality: Optional[str]
    sub_locality: Optional[str]
    street: Optional[str]
    formatted_address: Optional[str]
    raw: dict[str, Any] = field(default_factory=dict)


def parse_reverse_geocode(body: Any, http_status: int | None = None) -> ReverseGeocodeResult:
    _raise_if_error(body, http_status)
    if not isinstance(body, dict):
        raise ProviderError(INVALID_RESPONSE, "non-object reverse geocode body")
    results = body.get("results") or []
    if not results:
        raise ProviderError(EMPTY_RESULT, "no reverse geocode results")
    r0 = results[0]
    return ReverseGeocodeResult(
        locality=r0.get("locality") or None,
        sub_locality=r0.get("subLocality") or None,
        street=r0.get("street") or None,
        formatted_address=r0.get("formatted_address") or r0.get("formattedAddress") or None,
        raw=r0,
    )
