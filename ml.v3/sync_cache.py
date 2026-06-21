"""
ml.v3/sync_cache.py — push the LOCAL static JSON cache into MongoDB, and print
cache stats.

    python ml.v3/sync_cache.py          # mirror local static cache -> Mongo
    python ml.v3/sync_cache.py --stats  # just print counts

Static entries (POI/geocode/snap/...) live in local JSON first; this mirrors them
to MongoDB so other machines / deploys share the durable cache. Live entries are
already Mongo-only (TTL) and are not touched here.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # ml.v3
import config as C          # noqa: E402,F401  (ensures .env is loaded)
from cache import cache     # noqa: E402


def main():
    if "--stats" in sys.argv:
        print("[sync_cache] stats:", cache.stats())
        return
    n = cache.sync_local_to_mongo()
    print(f"[sync_cache] mirrored {n} static entries -> MongoDB")
    print("[sync_cache] stats:", cache.stats())


if __name__ == "__main__":
    main()
