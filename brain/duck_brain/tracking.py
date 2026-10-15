"""Fast reflex loop: follow faces with the eyes and head, no LLM involved.

The camera sits in the duck's head, so it moves with the head: a face's pixel
offset from the image centre is an angular error relative to where the head
points now. Each step corrects a fraction of that error (P-control with a
deadband); the eyes take the small, quick part of the motion.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Optional

import cv2
import numpy as np

from .robot import Robot, RobotOffline
from .trace import Trace


class FaceTracker:
    def __init__(self, cfg: dict[str, Any], stream: str, robot: Robot, trace: Trace,
                 on_new_face: Callable[[], Awaitable[None]]) -> None:
        self.cfg = cfg
        self.stream = stream
        self.robot = robot
        self.trace = trace
        self.on_new_face = on_new_face
        self.enabled = bool(cfg.get("enabled", True))
        self.paused_until = 0.0  # gestures from Gemma pause tracking briefly
        cascade = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        self.detector = cv2.CascadeClassifier(cascade)
        self.yaw = 0.0
        self.pitch = 0.0
        self.last_seen = 0.0
        self.face_present = False
        self.centred_after_loss = True

    def pause(self, seconds: float) -> None:
        self.paused_until = max(self.paused_until, time.monotonic() + seconds)

    def sync_pose(self, yaw: float, pitch: float) -> None:
        self.yaw, self.pitch = yaw, pitch

    def detect(self, jpeg: bytes) -> Optional[tuple[float, float, float]]:
        """Largest face as (x, y, size), x/y normalised to -1..1 from the image centre."""
        img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_GRAYSCALE)
        if img is None:
            return None
        h, w = img.shape
        scale = 320 / w if w > 320 else 1.0
        small = cv2.resize(img, (int(w * scale), int(h * scale))) if scale != 1.0 else img
        faces = self.detector.detectMultiScale(small, scaleFactor=1.15, minNeighbors=5, minSize=(28, 28))
        if len(faces) == 0:
            return None
        x, y, fw, fh = max(faces, key=lambda f: f[2] * f[3])
        sh, sw = small.shape
        cx = (x + fw / 2) / sw * 2 - 1
        cy = (y + fh / 2) / sh * 2 - 1
        return float(cx), float(cy), float(fw / sw)

    async def run(self) -> None:
        period = 1.0 / float(self.cfg.get("rate_hz", 6))
        hfov = float(self.cfg.get("horizontal_fov_deg", 62))
        vfov = float(self.cfg.get("vertical_fov_deg", 48))
        gain = float(self.cfg.get("gain", 0.35))
        deadband = float(self.cfg.get("deadband", 0.12))
        greet_gap = float(self.cfg.get("greet_after_absent_s", 20))
        center_after = float(self.cfg.get("center_after_lost_s", 8))
        while True:
            await asyncio.sleep(period)
            if not self.enabled or time.monotonic() < self.paused_until:
                continue
            try:
                jpeg = await self.robot.snapshot_jpeg(self.stream)
                if jpeg is None:
                    continue
                face = await asyncio.to_thread(self.detect, jpeg)
                now = time.monotonic()
                if face is None:
                    if self.face_present and now - self.last_seen > 1.5:
                        self.face_present = False
                        self.trace.set_state(face=False)
                    if not self.centred_after_loss and now - self.last_seen > center_after:
                        self.centred_after_loss = True
                        self.yaw = self.pitch = 0.0
                        await self.robot.post("/api/head/center")
                    continue

                cx, cy, size = face
                if not self.face_present:
                    absent_for = now - self.last_seen if self.last_seen else 1e9
                    self.face_present = True
                    self.trace.set_state(face=True)
                    if self.cfg.get("greet_on_face", True) and absent_for > greet_gap:
                        self.trace.emit("reflex", detail="new face in view")
                        asyncio.create_task(self.on_new_face())
                self.last_seen = now
                self.centred_after_loss = False

                # Eyes: quick, small correction toward the face.
                ex = max(-1.0, min(1.0, cx * float(self.cfg.get("eyes_x_sign", 1))))
                await self.robot.post("/api/eyes/look", {"x": round(ex, 2), "y": round(max(-1, min(1, cy)), 2), "hold_s": 2})

                # Head: proportional step toward the face, ignoring small errors.
                if abs(cx) > deadband or abs(cy) > deadband:
                    dyaw = float(self.cfg.get("yaw_sign", -1)) * cx * (hfov / 2) * gain if abs(cx) > deadband else 0.0
                    dpitch = float(self.cfg.get("pitch_sign", 1)) * cy * (vfov / 2) * gain if abs(cy) > deadband else 0.0
                    self.yaw = max(-60.0, min(60.0, self.yaw + dyaw))
                    self.pitch = max(-40.0, min(30.0, self.pitch + dpitch))
                    await self.robot.post("/api/head/look_at", {"yaw": round(self.yaw, 1), "pitch": round(self.pitch, 1)})
            except RobotOffline:
                await asyncio.sleep(2)
            except Exception as exc:  # noqa: BLE001
                self.trace.emit("reflex", status="error", detail=f"tracking: {exc}")
                await asyncio.sleep(2)
