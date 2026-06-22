"""Enforceable API request budgets.

Every live request must be counted *before* execution. If the next request would
exceed any configured budget, the caller is told status = BLOCKED_API_BUDGET and
must not issue the request. Quota balance from Mappls is unknown (no rate-limit
headers), so we never invent remaining-credit values.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

BLOCKED = "BLOCKED_API_BUDGET"
ALLOWED = "ALLOWED"


class BudgetExceeded(RuntimeError):
    def __init__(self, scope: str, message: str):
        super().__init__(f"{BLOCKED}:{scope}: {message}")
        self.scope = scope


@dataclass
class ApiBudget:
    maximum_prepare_requests_per_run: int
    maximum_requests_per_poll_cycle: int
    maximum_route_eta_fallbacks_per_cycle: int
    maximum_requests_per_day: int
    stop_before_budget_exceeded: bool = True

    # counters
    prepare_used: int = 0
    cycle_used: int = 0
    cycle_fallbacks_used: int = 0
    day_used: int = 0
    attempted: int = 0
    completed: int = 0
    failed: int = 0
    retried: int = 0
    fallback_requests: int = 0
    blocked_events: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "ApiBudget":
        b = config["api_budget"]
        return cls(
            maximum_prepare_requests_per_run=int(b["maximum_prepare_requests_per_run"]),
            maximum_requests_per_poll_cycle=int(b["maximum_requests_per_poll_cycle"]),
            maximum_route_eta_fallbacks_per_cycle=int(
                b.get("maximum_route_eta_fallbacks_per_cycle", 3)
            ),
            maximum_requests_per_day=int(b["maximum_requests_per_day"]),
            stop_before_budget_exceeded=bool(b.get("stop_before_budget_exceeded", True)),
        )

    def reset_cycle(self) -> None:
        self.cycle_used = 0
        self.cycle_fallbacks_used = 0

    def _would_exceed(self, scope: str, is_fallback: bool) -> str | None:
        if self.day_used + 1 > self.maximum_requests_per_day:
            return "daily"
        if scope == "prepare" and self.prepare_used + 1 > self.maximum_prepare_requests_per_run:
            return "prepare"
        if scope == "poll":
            if self.cycle_used + 1 > self.maximum_requests_per_poll_cycle:
                return "poll_cycle"
            if is_fallback and self.cycle_fallbacks_used + 1 > self.maximum_route_eta_fallbacks_per_cycle:
                return "fallback"
        return None

    def check(self, scope: str = "poll", is_fallback: bool = False) -> str:
        """Return ALLOWED or BLOCKED without mutating counters."""
        exceeded = self._would_exceed(scope, is_fallback)
        return BLOCKED if exceeded else ALLOWED

    def reserve(self, scope: str = "poll", is_fallback: bool = False) -> None:
        """Count a request before execution. Raises BudgetExceeded if it would exceed."""
        exceeded = self._would_exceed(scope, is_fallback)
        if exceeded is not None:
            self.blocked_events.append({"scope": scope, "limit": exceeded, "is_fallback": is_fallback})
            if self.stop_before_budget_exceeded:
                raise BudgetExceeded(exceeded, f"would exceed {exceeded} budget")
        self.attempted += 1
        self.day_used += 1
        if scope == "prepare":
            self.prepare_used += 1
        elif scope == "poll":
            self.cycle_used += 1
            if is_fallback:
                self.cycle_fallbacks_used += 1
        if is_fallback:
            self.fallback_requests += 1

    def mark_completed(self) -> None:
        self.completed += 1

    def mark_failed(self) -> None:
        self.failed += 1

    def mark_retried(self) -> None:
        self.retried += 1

    def report(self) -> dict[str, Any]:
        return {
            "requests_attempted": self.attempted,
            "requests_completed": self.completed,
            "requests_failed": self.failed,
            "requests_retried": self.retried,
            "fallback_requests": self.fallback_requests,
            "prepare_used": self.prepare_used,
            "poll_cycle_used": self.cycle_used,
            "day_used": self.day_used,
            "request_budget_exceeded": bool(self.blocked_events),
            "blocked_events": self.blocked_events,
            "limits": {
                "maximum_prepare_requests_per_run": self.maximum_prepare_requests_per_run,
                "maximum_requests_per_poll_cycle": self.maximum_requests_per_poll_cycle,
                "maximum_route_eta_fallbacks_per_cycle": self.maximum_route_eta_fallbacks_per_cycle,
                "maximum_requests_per_day": self.maximum_requests_per_day,
            },
            "quota_balance_known": False,
        }
