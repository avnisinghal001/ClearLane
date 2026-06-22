"""Mappls transport: a single place where HTTP happens (or is replayed).

All adapters go through `MapplsClient.call`, which centralizes credential
injection, timeout, retry, latency/attempt accounting, response sanitization, and
budget reservation. In REPLAY mode no network is touched — fixtures are read from
disk and the data_mode is forced to REPLAY so replayed data can never be labelled
live.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .api_budget import ApiBudget, BudgetExceeded
from .common import redact, sha256_text
from .mappls_auth import Credentials
from .response_parsers import classify_error
from .retry_policy import decide

LIVE = "LIVE"
REPLAY = "REPLAY"


@dataclass
class RawResponse:
    operation: str
    http_status: Optional[int]
    body: Any
    provider_status: Optional[str]
    latency_ms: float
    attempt_count: int
    data_mode: str
    network_error: bool = False
    sanitized_sha256: str = ""
    provider_request_id: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.http_status == 200 and self.provider_status is None and not self.network_error

    def sanitized_body(self) -> Any:
        return redact(self.body)


class MapplsClient:
    def __init__(
        self,
        config: dict[str, Any],
        credentials: Credentials,
        *,
        data_mode: str = LIVE,
        replay_dir: Optional[str | Path] = None,
        budget: Optional[ApiBudget] = None,
        transport: Any = None,
    ):
        self.config = config
        self.credentials = credentials
        self.data_mode = REPLAY if data_mode == REPLAY else LIVE
        self.replay_dir = Path(replay_dir) if replay_dir else None
        self.budget = budget
        self._transport = transport  # injectable callable(url, params)->(status, body) for tests
        self.base_url = config["mappls"]["base_url"].rstrip("/")
        req = config["mappls"]["request"]
        self.timeout = float(req["timeout_seconds"])
        self.max_attempts = int(req["maximum_attempts"])
        self.backoff_initial = float(req["backoff_initial_seconds"])
        self.backoff_max = float(req["backoff_maximum_seconds"])
        self._httpx = None
        self.call_history: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ URLs
    def build_url(self, path: str) -> str:
        """Return a Mappls URL.

        Live Mappls route/search APIs used by Phase 3 accept the static key as
        the `access_token` query parameter. The key must not be embedded in the
        URL path.
        """
        if path.startswith(("http://", "https://")):
            return path
        return f"{self.base_url}/{path.lstrip('/')}"

    def route_url(self, path: str) -> str:
        base = self.config["mappls"].get("route_base_url", self.base_url).rstrip("/")
        return f"{base}/{path.lstrip('/')}"

    def search_url(self, path: str) -> str:
        base = self.config["mappls"].get("search_base_url", "https://search.mappls.com/search").rstrip("/")
        return f"{base}/{path.lstrip('/')}"

    def region(self, *, upper: bool = False) -> str:
        value = str(self.config["mappls"].get("default_region", "ind"))
        return value.upper() if upper else value.lower()

    def authorized_params(self, params: dict[str, Any]) -> dict[str, Any]:
        out = dict(params)
        out.setdefault("access_token", self.credentials.require_rest_key())
        return out

    # -------------------------------------------------------------- replay IO
    def _replay_body(self, operation: str) -> tuple[int, Any]:
        if self.replay_dir is None:
            raise FileNotFoundError("replay_dir not set")
        # support both <op>.json and <op>.response.json
        for name in (f"{operation}.json", f"{operation}.response.json"):
            p = self.replay_dir / name
            if p.exists():
                raw = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(raw, dict) and "body" in raw and "http_status" in raw:
                    return int(raw["http_status"]), raw["body"]
                return 200, raw
        raise FileNotFoundError(f"No replay fixture for operation {operation!r} in {self.replay_dir}")

    # ----------------------------------------------------------------- httpx
    def _http_get(self, url: str, params: dict[str, Any]) -> tuple[int, Any, bool]:
        if self._transport is not None:
            status, body = self._transport(url, params)
            return status, body, False
        if self._httpx is None:
            import httpx  # lazy

            self._httpx = httpx
        try:
            resp = self._httpx.get(url, params=params, timeout=self.timeout)
        except Exception:  # network/timeout
            return 0, None, True
        try:
            body: Any = resp.json()
        except Exception:
            body = resp.text
        return resp.status_code, body, False

    # ------------------------------------------------------------------ call
    def call(
        self,
        operation: str,
        path: str,
        params: Optional[dict[str, Any]] = None,
        *,
        budget_scope: str = "poll",
        is_fallback: bool = False,
    ) -> RawResponse:
        params = params or {}
        start = time.perf_counter()
        attempt = 0
        last_status: Optional[int] = None
        last_body: Any = None
        last_provider: Optional[str] = None
        network_error = False
        url: Optional[str] = None
        request_params: dict[str, Any] = {}

        # Budget reservation happens once, before execution.
        if self.budget is not None and self.data_mode == LIVE:
            self.budget.reserve(scope=budget_scope, is_fallback=is_fallback)

        while True:
            attempt += 1
            if self.data_mode == REPLAY:
                try:
                    last_status, last_body = self._replay_body(operation)
                    network_error = False
                except FileNotFoundError:
                    last_status, last_body, network_error = None, None, True
            else:
                url = self.build_url(path)
                request_params = self.authorized_params(params)
                last_status, last_body, network_error = self._http_get(url, request_params)

            last_provider = (
                None if network_error else classify_error(last_body, last_status)
            )
            retry_after = None
            if isinstance(last_body, dict):
                retry_after = last_body.get("retry_after")

            if last_status == 200 and last_provider is None and not network_error:
                break  # success

            decision = decide(
                attempt=attempt,
                max_attempts=self.max_attempts,
                http_status=last_status,
                provider_status=last_provider,
                network_error=network_error,
                timeout=False,
                retry_after=retry_after,
                initial=self.backoff_initial,
                maximum=self.backoff_max,
            )
            if self.budget is not None and decision.should_retry:
                self.budget.mark_retried()
            if not decision.should_retry:
                break
            if self.data_mode == LIVE and decision.delay_seconds > 0:
                time.sleep(min(decision.delay_seconds, self.backoff_max))

        latency_ms = (time.perf_counter() - start) * 1000.0
        sanitized = redact(last_body)
        sha = sha256_text(json.dumps(sanitized, sort_keys=True, default=str))
        provider_request_id = None
        if isinstance(last_body, dict):
            provider_request_id = last_body.get("Server") or last_body.get("version")

        resp = RawResponse(
            operation=operation,
            http_status=last_status,
            body=last_body,
            provider_status=last_provider,
            latency_ms=latency_ms,
            attempt_count=attempt,
            data_mode=self.data_mode,
            network_error=network_error,
            sanitized_sha256=sha,
            provider_request_id=str(provider_request_id) if provider_request_id else None,
        )
        if self.budget is not None and self.data_mode == LIVE:
            if resp.ok:
                self.budget.mark_completed()
            else:
                self.budget.mark_failed()
        self.call_history.append(
            {
                "operation": operation,
                "data_mode": self.data_mode,
                "hit_mappls_api": bool(self.data_mode == LIVE),
                "budget_scope": budget_scope,
                "is_fallback": bool(is_fallback),
                "url": redact(url) if url else None,
                "params": redact(request_params),
                "http_status": resp.http_status,
                "provider_status": resp.provider_status,
                "ok": resp.ok,
                "network_error": resp.network_error,
                "attempt_count": resp.attempt_count,
                "latency_ms": round(resp.latency_ms, 2),
                "sanitized_response_sha256": resp.sanitized_sha256,
            }
        )
        return resp

    def request_summary(self) -> dict[str, Any]:
        """Presence/metadata-only request summary. Never includes credentials."""
        operations: dict[str, int] = {}
        statuses: dict[str, int] = {}
        for h in self.call_history:
            operations[h["operation"]] = operations.get(h["operation"], 0) + 1
            status = h.get("provider_status") or f"HTTP_{h.get('http_status')}"
            statuses[str(status)] = statuses.get(str(status), 0) + 1
        return {
            "total_calls_recorded": len(self.call_history),
            "live_mappls_api_calls_attempted": sum(1 for h in self.call_history if h.get("hit_mappls_api")),
            "replay_fixture_reads": sum(1 for h in self.call_history if h.get("data_mode") == REPLAY),
            "operations": operations,
            "status_counts": statuses,
        }
