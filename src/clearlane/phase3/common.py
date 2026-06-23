"""Shared Phase 3 helpers: repo paths, config loading, run IDs, time, and
credential redaction.

Credential redaction lives here because *every* Phase 3 surface (logs, reports,
exceptions, sanitized fixtures) must route through it. The forbidden-field list
is defined once and reused everywhere.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

IST = ZoneInfo("Asia/Kolkata")

# Field names whose values must never appear in any Phase 3 output.
REDACT_KEYS = {
    "token",
    "access_token",
    "authorization",
    "client_secret",
    "client_id",
    "bearer",
    "api_key",
    "apikey",
    "rest_key",
    "restkey",
    "key",
}

_REDACTED = "***REDACTED***"


def repo_root(start: str | Path | None = None) -> Path:
    p = Path(start or Path.cwd()).resolve()
    for cur in [p, *p.parents]:
        if (cur / ".git").exists() or (cur / "vercel.json").exists():
            return cur
    return p


def load_config(path: str | Path = "configs/phase3.yaml",
                root: str | Path | None = None) -> dict[str, Any]:
    root_path = repo_root(root)
    p = Path(path)
    if not p.is_absolute():
        p = root_path / p
    with p.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    config["_config_path"] = str(p)
    config["_repo_root"] = str(root_path)
    return config


def make_run_id(prefix: str = "phase3") -> str:
    return datetime.now(IST).strftime(f"%Y%m%d_%H%M%S_{prefix}")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_ist() -> datetime:
    return datetime.now(IST)


def to_ist(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST)


def observation_bucket(dt: datetime, bucket_minutes: int = 15) -> str:
    """Floor a timestamp (IST) to a fixed bucket and return an ISO-ish label."""
    ist = to_ist(dt)
    minute = (ist.minute // bucket_minutes) * bucket_minutes
    floored = ist.replace(minute=minute, second=0, microsecond=0)
    return floored.strftime("%Y-%m-%dT%H:%M:%S%z")


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def redact(value: Any) -> Any:
    """Recursively redact credential-bearing fields from any JSON-like value.

    Also scrubs query strings / bearer headers that embed credentials inline.
    """
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if isinstance(k, str) and k.lower() in REDACT_KEYS:
                out[k] = _REDACTED
            else:
                out[k] = redact(v)
        return out
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return _redact_string(value)
    return value


_BEARER_RE = re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+")
_QUERY_SECRET_RE = re.compile(
    r"(?i)(access_token|client_secret|client_id|api_key|rest_key|token|key)=([^&\s]+)"
)
# Legacy Mappls clients embedded the REST key as a path segment. Keep scrubbing
# this shape so older artifacts/tests cannot leak credentials.
_REST_KEY_PATH_RE = re.compile(r"(/advancedmaps/v1/)([^/]+)(/)")


def _redact_string(s: str) -> str:
    s = _BEARER_RE.sub("bearer " + _REDACTED, s)
    s = _QUERY_SECRET_RE.sub(lambda m: f"{m.group(1)}={_REDACTED}", s)
    s = _REST_KEY_PATH_RE.sub(lambda m: f"{m.group(1)}{_REDACTED}{m.group(3)}", s)
    return s


def write_json(path: str | Path, payload: Any, *, redact_secrets: bool = True) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = redact(copy.deepcopy(payload)) if redact_secrets else payload
    p.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return p


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))
