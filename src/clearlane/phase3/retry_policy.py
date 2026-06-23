"""Retry policy decisions (pure, no sleeping here).

Auth/permission failures (401/403, INVALID_TOKEN, ACCESS_DENIED) are NOT retried.
429 honours Retry-After. 5xx / network / timeout retry with bounded exponential
backoff. Schema-invalid responses are not blindly retried.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .response_parsers import (
    ACCESS_DENIED,
    INVALID_RESPONSE,
    INVALID_TOKEN,
    RATE_LIMITED,
    UNAUTHORIZED,
)

NON_RETRYABLE_PROVIDER = {INVALID_TOKEN, ACCESS_DENIED, UNAUTHORIZED, INVALID_RESPONSE}


@dataclass
class RetryDecision:
    should_retry: bool
    delay_seconds: float
    reason: str


def backoff_delay(attempt: int, initial: float, maximum: float) -> float:
    """attempt is 1-based. Exponential: initial * 2^(attempt-1), capped at maximum."""
    return min(maximum * 1.0, initial * (2 ** max(0, attempt - 1)))


def decide(
    *,
    attempt: int,
    max_attempts: int,
    http_status: Optional[int] = None,
    provider_status: Optional[str] = None,
    network_error: bool = False,
    timeout: bool = False,
    retry_after: Optional[float] = None,
    initial: float = 1.0,
    maximum: float = 15.0,
) -> RetryDecision:
    if attempt >= max_attempts:
        return RetryDecision(False, 0.0, "MAX_ATTEMPTS_REACHED")

    if provider_status in NON_RETRYABLE_PROVIDER:
        return RetryDecision(False, 0.0, f"NON_RETRYABLE:{provider_status}")
    if http_status in (401, 403):
        return RetryDecision(False, 0.0, f"NON_RETRYABLE_HTTP:{http_status}")

    if http_status == 429 or provider_status == RATE_LIMITED:
        delay = retry_after if retry_after is not None else backoff_delay(attempt, initial, maximum)
        return RetryDecision(True, float(delay), "RATE_LIMITED_HONOR_RETRY_AFTER")

    if timeout:
        return RetryDecision(True, backoff_delay(attempt, initial, maximum), "TIMEOUT_RETRY")
    if network_error:
        return RetryDecision(True, backoff_delay(attempt, initial, maximum), "NETWORK_RETRY")
    if http_status is not None and 500 <= http_status < 600:
        return RetryDecision(True, backoff_delay(attempt, initial, maximum), "SERVER_ERROR_RETRY")

    return RetryDecision(False, 0.0, "NO_RETRY")
