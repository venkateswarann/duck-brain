"""Event log shown live in the trace UI (and printed to the console)."""

from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from typing import Any


class Trace:
    def __init__(self, keep: int = 300) -> None:
        self.events: deque[dict[str, Any]] = deque(maxlen=keep)
        self.state: dict[str, Any] = {}
        self._subscribers: set[asyncio.Queue] = set()

    def emit(self, kind: str, **data: Any) -> dict[str, Any]:
        event = {"ts": time.time(), "kind": kind, **data}
        self.events.append(event)
        self._fanout({"type": "event", "event": event})
        _print(event)
        return event

    def set_state(self, **values: Any) -> None:
        self.state.update(values)
        self._fanout({"type": "state", "state": self.state})

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def _fanout(self, msg: dict[str, Any]) -> None:
        for q in list(self._subscribers):
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(msg)


_COLOURS = {"blocked": "\033[31m", "clamped": "\033[33m", "estop": "\033[31;1m", "error": "\033[31m",
            "heard": "\033[36m", "say": "\033[32m"}


def _print(event: dict[str, Any]) -> None:
    kind = event["kind"]
    status = event.get("status", "")
    colour = _COLOURS.get(status) or _COLOURS.get(kind, "")
    body = {k: v for k, v in event.items() if k not in ("ts", "kind", "image_b64")}
    text = json.dumps(body, default=str)
    if len(text) > 300:
        text = text[:297] + "..."
    print(f"{colour}[{kind}]\033[0m {text}", flush=True)
