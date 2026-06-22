"""Localized slowdown signal (NOT proof of illegal parking).

    localized_anomaly = current_severity - median(valid monitored ring-1 neighbour severities)

Requires the same completed poll cycle and at least N valid monitored neighbours.
Sparse cells are not fabricated.
"""

from __future__ import annotations

import math
import statistics
from typing import Any, Optional

COMPUTED = "COMPUTED"
INSUFFICIENT = "INSUFFICIENT_VALID_NEIGHBORS"
CURRENT_INVALID = "CURRENT_CELL_INVALID"
NO_NEIGHBORS = "NO_MONITORED_NEIGHBORS"


def _valid(x: Optional[float]) -> bool:
    return x is not None and isinstance(x, (int, float)) and math.isfinite(x)


def compute_for_cell(
    current_severity: Optional[float],
    neighbor_severities: list[Optional[float]],
    *,
    minimum_valid_neighbors: int = 2,
) -> dict[str, Any]:
    total = len(neighbor_severities)
    valid_neighbors = [s for s in neighbor_severities if _valid(s)]
    result: dict[str, Any] = {
        "neighbor_count_total": total,
        "neighbor_count_valid": len(valid_neighbors),
        "neighbor_median_severity": None,
        "localized_anomaly": None,
        "localized_anomaly_positive": None,
        "localized_anomaly_status": None,
    }

    if not _valid(current_severity):
        result["localized_anomaly_status"] = CURRENT_INVALID
        return result
    if total == 0:
        result["localized_anomaly_status"] = NO_NEIGHBORS
        return result
    if len(valid_neighbors) < minimum_valid_neighbors:
        result["localized_anomaly_status"] = INSUFFICIENT
        return result

    median = statistics.median(valid_neighbors)
    anomaly = current_severity - median
    result["neighbor_median_severity"] = median
    result["localized_anomaly"] = anomaly
    result["localized_anomaly_positive"] = bool(anomaly > 0)
    result["localized_anomaly_status"] = COMPUTED
    return result


def ring1_neighbors(h3_index: str) -> list[str]:
    """Return the ring-1 (k=1) neighbours of an H3 cell, excluding itself."""
    try:
        import h3  # type: ignore
    except Exception:  # pragma: no cover
        return []
    try:
        if hasattr(h3, "grid_disk"):
            disk = h3.grid_disk(h3_index, 1)
        else:  # h3 v3
            disk = h3.k_ring(h3_index, 1)
    except Exception:
        return []
    return [c for c in disk if c != h3_index]
