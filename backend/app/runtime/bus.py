from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from typing import Any, Deque


class TelemetryBus:
    """In-memory fan-out bus for telemetry snapshots and node events."""

    def __init__(self, log_maxlen: int = 500) -> None:
        self._snapshot: dict[str, Any] = {
            "ts": time.time(),
            "motors": {},
            "nodes": {},
            "system": {},
            "video": {"running": False},
        }
        self._logs: dict[str, Deque[str]] = defaultdict(lambda: deque(maxlen=log_maxlen))
        self._subscribers: set[asyncio.Queue] = set()
        self._event_subscribers: set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()

    def get_snapshot(self) -> dict[str, Any]:
        return dict(self._snapshot)

    async def update(self, **sections: Any) -> None:
        async with self._lock:
            self._snapshot["ts"] = time.time()
            for key, value in sections.items():
                if isinstance(value, dict) and isinstance(self._snapshot.get(key), dict):
                    merged = dict(self._snapshot[key])
                    merged.update(value)
                    self._snapshot[key] = merged
                else:
                    self._snapshot[key] = value
            payload = dict(self._snapshot)
        await self._fanout(self._subscribers, payload)

    async def publish_event(self, event: dict[str, Any]) -> None:
        event = {**event, "ts": time.time()}
        await self._fanout(self._event_subscribers, event)

    def append_log(self, node_id: str, line: str) -> None:
        self._logs[node_id].append(line)

    def get_logs(self, node_id: str, limit: int = 200) -> list[str]:
        items = list(self._logs.get(node_id, []))
        return items[-limit:]

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=8)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def subscribe_events(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=32)
        self._event_subscribers.add(q)
        return q

    def unsubscribe_events(self, q: asyncio.Queue) -> None:
        self._event_subscribers.discard(q)

    async def _fanout(self, subscribers: set[asyncio.Queue], payload: dict[str, Any]) -> None:
        dead: list[asyncio.Queue] = []
        for q in list(subscribers):
            try:
                if q.full():
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                q.put_nowait(payload)
            except Exception:
                dead.append(q)
        for q in dead:
            subscribers.discard(q)
