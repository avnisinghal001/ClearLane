"""Mappls credential resolution.

Primary credential is the static REST key (`MAPPLS_REST_KEY`), used as a path
segment for the verified routing / matrix / geocode / snap APIs. OAuth client
credentials are optional. Credentials are never logged, serialized, or placed in
exceptions — only their presence is reported.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

try:  # optional: load .env if python-dotenv present
    from dotenv import load_dotenv  # type: ignore

    load_dotenv(override=False)
except Exception:  # pragma: no cover - dotenv optional
    pass


class AuthError(RuntimeError):
    pass


@dataclass
class Credentials:
    rest_key: Optional[str]
    client_id: Optional[str]
    client_secret: Optional[str]
    access_token: Optional[str]

    @property
    def has_rest_key(self) -> bool:
        return bool(self.rest_key)

    @property
    def has_oauth(self) -> bool:
        return bool(self.client_id and self.client_secret) or bool(self.access_token)

    def require_rest_key(self) -> str:
        if not self.rest_key:
            raise AuthError("MAPPLS_REST_KEY_MISSING")
        return self.rest_key

    def status_report(self) -> dict[str, Any]:
        """Presence-only report. NEVER contains credential values."""
        return {
            "rest_key_present": self.has_rest_key,
            "client_id_present": bool(self.client_id),
            "client_secret_present": bool(self.client_secret),
            "access_token_present": bool(self.access_token),
            "oauth_available": self.has_oauth,
            "primary_mode": "static_rest_key",
        }


def load_credentials(config: dict[str, Any], env: Optional[dict[str, str]] = None) -> Credentials:
    env = env if env is not None else os.environ
    auth = config["mappls"]["authentication"]
    return Credentials(
        rest_key=env.get(auth.get("rest_key_env", "MAPPLS_REST_KEY")) or None,
        client_id=env.get(auth.get("client_id_env", "MAPPLS_CLIENT_ID")) or None,
        client_secret=env.get(auth.get("client_secret_env", "MAPPLS_CLIENT_SECRET")) or None,
        access_token=env.get(auth.get("access_token_env", "MAPPLS_ACCESS_TOKEN")) or None,
    )
