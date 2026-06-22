"""ClearLane Phase 3 — Whitefield live traffic, congestion severity, and
parking-induced-congestion (PIC) ranking.

Phase 3 consumes ONLY verified Phase 2 outputs. It never reads the raw ticket
dataset, never re-runs Phase 2 modelling, and never claims to directly detect an
illegally parked vehicle. It adds a live, regional (Whitefield demo) traffic
layer on top of the citywide Bengaluru historical hotspot layer.
"""

PHASE3_ALGORITHM_VERSION = "phase3-v1"

__all__ = ["PHASE3_ALGORITHM_VERSION"]
