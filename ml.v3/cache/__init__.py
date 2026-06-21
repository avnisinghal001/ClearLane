"""
ml.v3/cache — two-tier Mappls cache (local JSON + MongoDB) behind an event bus.

Usage:
    from cache import cache
    data = cache.get_or_fetch("nearby", key, fetch_fn, live=False)   # static
    eta  = cache.get_or_fetch("eta",    key, fetch_fn, live=True, ttl=900)  # live
    cache.flush()                                                    # batch-persist

`cache` is a process-wide singleton. Mongo connects lazily and degrades to the
local-JSON tier if unreachable.
"""
from .cache import MapplsCache

cache = MapplsCache()


def flush() -> None:
    cache.flush()


__all__ = ["cache", "flush", "MapplsCache"]
