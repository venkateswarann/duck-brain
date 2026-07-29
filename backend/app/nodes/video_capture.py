from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

import numpy as np

from ..runtime.base_node import Node
from ..runtime.bus import TelemetryBus
from ..runtime.locks import ResourceLocks
from ..schemas import NodeState


class VideoCaptureNode(Node):
    """Camera node. Kill stops MJPEG stream consumers."""

    id = "video.capture"
    name = "Video Capture"
    kind = "sensors.camera"
    resources = ["camera0"]
    topics_out = ["video"]

    def __init__(self, bus: TelemetryBus, locks: ResourceLocks, device: int | str = 0) -> None:
        super().__init__(bus, locks)
        self._device = device
        self._cap: Any = None
        self._frame: Optional[bytes] = None
        self._frame_lock = asyncio.Lock()
        self._config = {"device": device, "width": 640, "height": 480, "mock": True}

    async def on_start(self) -> None:
        mock = True
        try:
            import cv2  # type: ignore

            cap = cv2.VideoCapture(self._device)
            if cap is not None and cap.isOpened():
                self._cap = cap
                self._config["mock"] = False
                mock = False
                self.log(f"opened camera device {self._device}")
            else:
                if cap is not None:
                    cap.release()
                self.log("camera device unavailable; using mock frames")
        except Exception as exc:  # noqa: BLE001
            self.log(f"opencv unavailable ({exc}); using mock frames")
        self._config["mock"] = mock
        self._task = asyncio.create_task(self._capture_loop(), name="video-capture")
        await self.bus.update(video={"running": True, "mock": mock})

    async def on_stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:  # noqa: BLE001
                pass
            self._cap = None
        async with self._frame_lock:
            self._frame = None
        await self.bus.update(video={"running": False})

    async def on_kill(self) -> None:
        # Ensure stream ends immediately
        async with self._frame_lock:
            self._frame = None
        await self.bus.update(video={"running": False, "killed": True})

    async def get_jpeg(self) -> Optional[bytes]:
        if self.state != NodeState.RUNNING:
            return None
        async with self._frame_lock:
            return self._frame

    async def _capture_loop(self) -> None:
        while True:
            jpeg = await asyncio.to_thread(self._grab)
            async with self._frame_lock:
                self._frame = jpeg
            await self.bus.update(
                video={"running": True, "mock": self._config.get("mock", True), "ts": time.time()}
            )
            await asyncio.sleep(1 / 15)

    def _grab(self) -> bytes:
        try:
            import cv2  # type: ignore
        except Exception:
            return self._mock_jpeg()

        if self._cap is not None and not self._config.get("mock"):
            ok, frame = self._cap.read()
            if ok and frame is not None:
                w = int(self._config.get("width", 640))
                h = int(self._config.get("height", 480))
                frame = cv2.resize(frame, (w, h))
                ok2, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
                if ok2:
                    return buf.tobytes()
        return self._mock_jpeg()

    def _mock_jpeg(self) -> bytes:
        try:
            import cv2  # type: ignore
        except Exception:
            # Minimal JPEG header-ish placeholder — clients treat as binary
            return b""

        w = int(self._config.get("width", 640))
        h = int(self._config.get("height", 480))
        img = np.zeros((h, w, 3), dtype=np.uint8)
        t = time.time()
        img[:, :] = (30, 30, 36)
        cv2.putText(
            img,
            "DCS Video Capture (mock)",
            (40, h // 2),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (80, 220, 140),
            2,
            cv2.LINE_AA,
        )
        cv2.putText(
            img,
            time.strftime("%H:%M:%S", time.localtime(t)),
            (40, h // 2 + 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (180, 180, 190),
            2,
            cv2.LINE_AA,
        )
        ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
        return buf.tobytes() if ok else b""
