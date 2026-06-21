"""
ml.v3/cache/bus.py — a tiny synchronous event bus for cache writes.

Every time the cache fetches a fresh value it `publish()`es a CacheEvent. Sinks
(local-JSON, MongoDB) subscribe and decide what to do:
  * a STATIC event -> the local sink buffers it AND the mongo sink buffers it,
  * a LIVE event   -> only the mongo sink buffers it (with a TTL).
Sinks buffer and write in bulk on `flush()` so we never hit Mongo per-call.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class CacheEvent:
    ns: str                      # namespace, e.g. "nearby" / "eta"
    key: str                     # cache key within the namespace
    value: object                # the JSON-serialisable payload to store
    live: bool = False           # live -> mongo-only + TTL; static -> local + mongo
    ttl: float | None = None     # seconds-to-live for live events
    ts: float = field(default_factory=time.time)


class Sink:
    """Interface a subscriber implements."""
    def handle(self, event: CacheEvent) -> None: ...
    def flush(self) -> None: ...


class EventBus:
    def __init__(self) -> None:
        self._subs: list[Sink] = []

    def subscribe(self, sink: Sink) -> None:
        self._subs.append(sink)

    def publish(self, event: CacheEvent) -> None:
        for s in self._subs:
            try:
                s.handle(event)
            except Exception:
                pass             # a failing sink must never break the pipeline

    def flush(self) -> None:
        for s in self._subs:
            try:
                s.flush()
            except Exception:
                pass
