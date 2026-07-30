"""Latest-frame store for video published by scripts.

Scripts run as separate processes, so they hand frames to the backend over HTTP
(see robot_scripts/dcs_sdk.py) and land here. The Camera page then reads them
through /stream/video/{stream_id} exactly like the built-in camera node.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Optional

MAX_FRAME_BYTES = 8_000_000
DEFAULT_TTL = 10.0


@dataclass
class Stream:
    id: str
    label: str
    jpeg: bytes = b""
    ts: float = 0.0
    first_ts: float = field(default_factory=time.time)
    seq: int = 0
    frames: int = 0
    width: int = 0
    height: int = 0
    publisher: str = ""
    event: asyncio.Event = field(default_factory=asyncio.Event)

    def fps(self) -> float:
        span = self.ts - self.first_ts
        if span <= 0 or self.frames < 2:
            return 0.0
        return round((self.frames - 1) / span, 1)

    def info(self, live: bool) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "kind": "script",
            "live": live,
            "frames": self.frames,
            "fps": self.fps(),
            "width": self.width,
            "height": self.height,
            "publisher": self.publisher,
            "last_frame_age": round(max(0.0, time.time() - self.ts), 2),
        }


class FrameHub:
    """Keeps only the newest frame per stream and wakes MJPEG consumers."""

    def __init__(self, ttl: float = DEFAULT_TTL) -> None:
        self.ttl = ttl
        self._streams: dict[str, Stream] = {}

    def publish(
        self,
        stream_id: str,
        jpeg: bytes,
        label: str = "",
        publisher: str = "",
        width: int = 0,
        height: int = 0,
    ) -> Stream:
        stream = self._streams.get(stream_id)
        if stream is None:
            stream = Stream(id=stream_id, label=label or stream_id)
            self._streams[stream_id] = stream
        if label:
            stream.label = label
        if publisher:
            stream.publisher = publisher
        if width and height:
            stream.width, stream.height = width, height
        stream.jpeg = jpeg
        stream.ts = time.time()
        stream.seq += 1
        stream.frames += 1
        waiters, stream.event = stream.event, asyncio.Event()
        waiters.set()
        return stream

    def is_live(self, stream: Stream) -> bool:
        return stream.ts > 0 and (time.time() - stream.ts) <= self.ttl

    def get(self, stream_id: str) -> Optional[Stream]:
        return self._streams.get(stream_id)

    def latest(self, stream_id: str) -> Optional[bytes]:
        stream = self._streams.get(stream_id)
        if stream is None or not stream.jpeg:
            return None
        return stream.jpeg

    def streams(self, include_stale: bool = False) -> list[dict[str, Any]]:
        self.prune()
        out = []
        for stream in self._streams.values():
            live = self.is_live(stream)
            if live or include_stale:
                out.append(stream.info(live))
        return sorted(out, key=lambda item: item["id"])

    def prune(self) -> None:
        """Forget streams whose publisher stopped, so the UI list stays honest."""
        cutoff = time.time() - max(self.ttl * 3, 30.0)
        for stream_id in [sid for sid, s in self._streams.items() if s.ts < cutoff]:
            self._streams.pop(stream_id, None)

    def drop(self, stream_id: str) -> None:
        self._streams.pop(stream_id, None)

    async def next_frame(
        self, stream_id: str, last_seq: int, timeout: float = 5.0
    ) -> Optional[tuple[int, bytes]]:
        """Newest frame for a consumer that already saw ``last_seq``."""
        stream = self._streams.get(stream_id)
        if stream is None:
            return None
        if stream.seq != last_seq and stream.jpeg:
            return stream.seq, stream.jpeg
        event = stream.event
        try:
            await asyncio.wait_for(event.wait(), timeout)
        except asyncio.TimeoutError:
            return None
        if not stream.jpeg:
            return None
        return stream.seq, stream.jpeg
