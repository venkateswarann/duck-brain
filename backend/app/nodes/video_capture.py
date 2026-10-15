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

    def __init__(self, bus: TelemetryBus, locks: ResourceLocks, config: Any = None, device: int | str = 0) -> None:
        super().__init__(bus, locks)
        self._duck_config = config
        dev = getattr(config, "camera_device", device) if config else device
        if isinstance(dev, str) and dev.isdigit():
            dev = int(dev)
        self._device = dev
        self._cap: Any = None
        self._picam2: Any = None
        self._frame: Optional[bytes] = None
        self._frame_lock = asyncio.Lock()
        w = getattr(config, "camera_width", 640) if config else 640
        h = getattr(config, "camera_height", 480) if config else 480
        rot = getattr(config, "camera_rotation", 0) if config else 0
        fps = getattr(config, "camera_fps", 15) if config else 15
        fh = getattr(config, "camera_flip_h", False) if config else False
        fv = getattr(config, "camera_flip_v", False) if config else False
        srb = getattr(config, "camera_swap_rb", False) if config else False
        mock_forced = getattr(config, "mock_hardware", False) if config else False
        self._config = {
            "device": dev,
            "width": w,
            "height": h,
            "rotation": rot,
            "fps": fps,
            "flip_h": fh,
            "flip_v": fv,
            "swap_rb": srb,
            "mock": True,
            "mock_forced": mock_forced,
        }

    async def on_config(self, config: dict[str, Any]) -> None:
        for k in ("device", "width", "height", "rotation", "fps", "flip_h", "flip_v", "swap_rb"):
            if k in config:
                self._config[k] = config[k]

    async def on_start(self) -> None:
        mock = True
        mock_forced = self._config.get("mock_forced", False)
        if mock_forced:
            self.log("mock_hardware is enabled in config; using mock camera frames. Set mock_hardware: false in config for live camera.")
        else:
            # 1. Try Picamera2 (Raspberry Pi libcamera)
            try:
                # picamera2 comes from apt (python3-picamera2); setup.sh builds the
                # venv with --system-site-packages on a Pi so this import just works.
                # (Appending dist-packages to sys.path mixed apt and venv numpy builds.)
                from picamera2 import Picamera2  # type: ignore
                from libcamera import Transform  # type: ignore

                if not Picamera2.global_camera_info():
                    raise RuntimeError("libcamera found no camera")
                picam2 = Picamera2()
                w = int(self._config.get("width", 640))
                h = int(self._config.get("height", 480))
                # Flips and 180 degrees are done for free in the ISP.
                rot180 = int(self._config.get("rotation", 0)) == 180
                transform = Transform(
                    hflip=bool(self._config.get("flip_h")) != rot180,
                    vflip=bool(self._config.get("flip_v")) != rot180,
                )
                cam_config = picam2.create_preview_configuration(
                    main={"format": "RGB888", "size": (w, h)}, transform=transform
                )
                picam2.configure(cam_config)
                picam2.start()
                self._picam2 = picam2
                mock = False
                self.log("opened camera using Picamera2 (Raspberry Pi libcamera)")
            except Exception as picam_exc:  # noqa: BLE001
                self.log(f"picamera2 unavailable or failed ({picam_exc}); trying OpenCV...")

                # 2. Try OpenCV cv2.VideoCapture
                try:
                    import cv2  # type: ignore

                    dev = self._device
                    cap = None
                    if hasattr(cv2, "CAP_V4L2"):
                        cap = cv2.VideoCapture(dev, cv2.CAP_V4L2)
                    if cap is None or not cap.isOpened():
                        if cap is not None:
                            cap.release()
                        cap = cv2.VideoCapture(dev)
                    
                    if (cap is None or not cap.isOpened()) and isinstance(dev, int):
                        dev_path = f"/dev/video{dev}"
                        if hasattr(cv2, "CAP_V4L2"):
                            cap = cv2.VideoCapture(dev_path, cv2.CAP_V4L2)
                        if cap is None or not cap.isOpened():
                            if cap is not None:
                                cap.release()
                            cap = cv2.VideoCapture(dev_path)

                    if cap is not None and cap.isOpened():
                        self._cap = cap
                        mock = False
                        self.log(f"opened camera device {self._device} via OpenCV")
                    else:
                        if cap is not None:
                            cap.release()
                        self.log(f"camera device {self._device} unavailable via OpenCV; using mock frames")
                except Exception as cv_exc:  # noqa: BLE001
                    self.log(f"opencv unavailable ({cv_exc}); using mock frames. Install opencv-python or picamera2.")

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
        if self._picam2 is not None:
            try:
                self._picam2.stop()
                self._picam2.close()
            except Exception:  # noqa: BLE001
                pass
            self._picam2 = None
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
            fps = max(1, min(60, int(self._config.get("fps", 15))))
            await asyncio.sleep(1 / fps)

    def _transform_frame(self, frame: Any, isp_done: bool = False) -> Any:
        """Rotate/flip in software; isp_done means Picamera2 already did flips and 180."""
        try:
            import cv2  # type: ignore
        except Exception:
            return frame

        rot = int(self._config.get("rotation", 0))
        if rot == 180 and not isp_done:
            frame = cv2.rotate(frame, cv2.ROTATE_180)
        elif rot == 90:
            frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        elif rot == 270:
            frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

        if self._config.get("flip_h") and not isp_done:
            frame = cv2.flip(frame, 1)
        if self._config.get("flip_v") and not isp_done:
            frame = cv2.flip(frame, 0)
        if self._config.get("swap_rb"):
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return frame

    def _grab(self) -> bytes:
        if self._picam2 is not None and not self._config.get("mock"):
            try:
                import cv2  # type: ignore
                frame = self._picam2.capture_array()
                if frame is not None:
                    # libcamera's "RGB888" is already B,G,R in memory, which is what
                    # OpenCV wants; converting it swapped red and blue.
                    if len(frame.shape) == 3 and frame.shape[2] == 4:
                        frame = frame[:, :, :3]
                    frame = self._transform_frame(frame, isp_done=True)
                    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
                    if ok:
                        return buf.tobytes()
            except Exception as exc:  # noqa: BLE001
                self.log(f"picam2 capture timeout or hardware error: {exc}")

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
                frame = self._transform_frame(frame)
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
