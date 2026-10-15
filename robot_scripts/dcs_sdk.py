"""Helper library for robot scripts, importable from anywhere under robot_scripts/.

Standard library only, so a script that uses it still runs when you launch it by
hand over SSH instead of from the DCS Scripts page.

Publishing video to the Camera page::

    from dcs_sdk import VideoStream

    cam = VideoStream("usb_cam", label="USB Camera", fps=15)
    while True:
        ok, frame = cap.read()
        cam.publish_frame(frame)      # numpy BGR array (needs cv2)
        cam.wait_for_next_frame()     # paces the loop to fps

``publish_jpeg(bytes)`` is there when you already have encoded data. The stream
shows up in the Camera page Source dropdown while frames keep arriving.

Environment set by DCS when it starts a script (all optional):
    DCS_API_URL    backend base URL, default http://127.0.0.1:8000
    DCS_STREAM_ID  default stream id, derived from the script filename
    DCS_NODE_ID    node id of the running script
"""

from __future__ import annotations

import http.client
import os
import sys
import time
import urllib.parse
from typing import Any, Optional

__all__ = ["VideoStream", "api_url", "find_backend", "node_id", "default_stream_id", "log"]

DEFAULT_API_URL = "http://127.0.0.1:8000"
WARN_INTERVAL = 10.0


def api_url() -> str:
    return os.environ.get("DCS_API_URL") or DEFAULT_API_URL


def find_backend(candidates: list[str], timeout: float = 1.5) -> Optional[str]:
    """Return the first base URL whose /api/health answers, or None.

    Lets one config list LAN, USB-link and Tailscale addresses for the same
    backend; whichever network is up at the time wins.
    """
    for base in candidates:
        parsed = urllib.parse.urlsplit(base)
        factory = (
            http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
        )
        try:
            conn = factory(parsed.hostname or "127.0.0.1", parsed.port, timeout=timeout)
            conn.request("GET", parsed.path.rstrip("/") + "/api/health")
            ok = conn.getresponse().status == 200
            conn.close()
        except (OSError, http.client.HTTPException):
            ok = False
        if ok:
            return base.rstrip("/")
    return None


def node_id() -> str:
    return os.environ.get("DCS_NODE_ID", "")


def default_stream_id() -> str:
    env = os.environ.get("DCS_STREAM_ID")
    if env:
        return env
    stem = os.path.splitext(os.path.basename(sys.argv[0] or "script"))[0]
    return stem or "script"


def log(*parts: Any) -> None:
    """Print a line that shows up in the script's DCS log panel."""
    print(*parts, flush=True)


class VideoStream:
    """Pushes JPEG frames to the DCS backend so the Camera page can show them."""

    def __init__(
        self,
        stream_id: Optional[str] = None,
        label: str = "",
        fps: float = 15.0,
        quality: int = 70,
        base_url: Optional[str] = None,
        timeout: float = 2.0,
    ) -> None:
        self.id = (stream_id or default_stream_id()).strip()
        self.label = label or self.id
        self.fps = max(0.1, float(fps))
        self.quality = max(10, min(95, int(quality)))
        self.timeout = timeout
        self.frames_sent = 0
        self.errors = 0

        parsed = urllib.parse.urlsplit(base_url or api_url())
        self._https = parsed.scheme == "https"
        self._host = parsed.hostname or "127.0.0.1"
        self._port = parsed.port or (443 if self._https else 80)
        self._prefix = parsed.path.rstrip("/")
        self._conn: Optional[http.client.HTTPConnection] = None
        self._next_frame_at = time.monotonic()
        self._last_warn = 0.0

    # ------------------------------------------------------------------ #

    def publish_jpeg(self, jpeg: bytes, width: int = 0, height: int = 0) -> bool:
        """Send one already-encoded JPEG frame. Never raises."""
        if not jpeg:
            return False
        query = urllib.parse.urlencode(
            {
                "label": self.label,
                "publisher": node_id() or os.path.basename(sys.argv[0] or ""),
                "width": int(width),
                "height": int(height),
            }
        )
        path = f"{self._prefix}/api/video/ingest/{urllib.parse.quote(self.id)}?{query}"
        for attempt in (1, 2):
            try:
                conn = self._connection()
                conn.request(
                    "POST",
                    path,
                    body=jpeg,
                    headers={
                        "Content-Type": "image/jpeg",
                        "Content-Length": str(len(jpeg)),
                    },
                )
                response = conn.getresponse()
                response.read()
                if response.status >= 400:
                    self._warn(f"ingest rejected frame: HTTP {response.status}")
                    self.errors += 1
                    return False
                self.frames_sent += 1
                return True
            except (OSError, http.client.HTTPException) as exc:
                self._close()
                if attempt == 2:
                    self.errors += 1
                    self._warn(f"cannot reach DCS at {self._host}:{self._port} ({exc})")
        return False

    def publish_frame(self, frame: Any, quality: Optional[int] = None) -> bool:
        """Encode a numpy BGR image with cv2 and publish it."""
        try:
            import cv2  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on the robot image
            raise RuntimeError(
                "publish_frame needs opencv (pip install opencv-python-headless); "
                "use publish_jpeg() if you encode frames yourself"
            ) from exc
        if frame is None:
            return False
        params = [int(cv2.IMWRITE_JPEG_QUALITY), int(quality or self.quality)]
        ok, buf = cv2.imencode(".jpg", frame, params)
        if not ok:
            self._warn("cv2.imencode failed")
            return False
        height, width = frame.shape[0], frame.shape[1]
        return self.publish_jpeg(buf.tobytes(), width=width, height=height)

    def wait_for_next_frame(self) -> None:
        """Sleep just long enough to hold the configured frame rate."""
        interval = 1.0 / self.fps
        now = time.monotonic()
        if self._next_frame_at < now:
            self._next_frame_at = now
        self._next_frame_at += interval
        delay = self._next_frame_at - now
        if delay > 0:
            time.sleep(delay)

    def close(self) -> None:
        self._close()

    def __enter__(self) -> "VideoStream":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    # ------------------------------------------------------------------ #

    def _connection(self) -> http.client.HTTPConnection:
        if self._conn is None:
            factory = (
                http.client.HTTPSConnection if self._https else http.client.HTTPConnection
            )
            self._conn = factory(self._host, self._port, timeout=self.timeout)
        return self._conn

    def _close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass
            self._conn = None

    def _warn(self, message: str) -> None:
        now = time.monotonic()
        if now - self._last_warn < WARN_INTERVAL:
            return
        self._last_warn = now
        print(f"[dcs_sdk] {message}", file=sys.stderr, flush=True)
