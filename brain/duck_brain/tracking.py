"""Fast reflex loop: follow faces with the eyes and head, no LLM involved.

The camera sits in the duck's head, so a face's pixel offset is an angle
relative to where the head points *now*. Each frame we read the head's measured
angle, add the face's offset to get where the face actually is, smooth that aim
point, and send it as an absolute target. The robot's spring-damper motion
blends these frequent small updates into one continuous glide. The eyes jump to
the face first and the head follows, like a person turning to look.
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
        self.aim: Optional[tuple[float, float]] = None  # smoothed absolute face direction
        self.sent: Optional[tuple[float, float]] = None
        self.last_seen = 0.0
        self.face_present = False
        self.centred_after_loss = True

    def pause(self, seconds: float) -> None:
        self.paused_until = max(self.paused_until, time.monotonic() + seconds)

    def sync_pose(self, yaw: float, pitch: float) -> None:
        self.yaw, self.pitch = yaw, pitch
        self.aim = self.sent = None

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
        gain = float(self.cfg.get("gain", 0.6))
        deadband = float(self.cfg.get("deadband", 0.08))
        smooth = float(self.cfg.get("smoothing", 0.5))  # 0 = raw, closer to 1 = smoother/slower
        min_step = float(self.cfg.get("min_step_deg", 0.5))
        greet_gap = float(self.cfg.get("greet_after_absent_s", 20))
        center_after = float(self.cfg.get("center_after_lost_s", 8))
        while True:
            await asyncio.sleep(period)
            if not self.enabled or time.monotonic() < self.paused_until:
                continue
            try:
                jpeg, head = await asyncio.gather(
                    self.robot.snapshot_jpeg(self.stream), self.robot.get("/api/head/state"))
                if jpeg is None:
                    continue
                present = head.get("present_deg", {}) if isinstance(head, dict) else {}
                face = await asyncio.to_thread(self.detect, jpeg)
                now = time.monotonic()
                if face is None:
                    if self.face_present and now - self.last_seen > 1.5:
                        self.face_present = False
                        self.trace.set_state(face=False)
                    if not self.centred_after_loss and now - self.last_seen > center_after:
                        self.centred_after_loss = True
                        self.yaw = self.pitch = 0.0
                        self.aim = self.sent = None
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

                # Head: aim at where the face is (measured head angle + its offset in the
                # image), smoothed; the robot's motion profile does the gliding.
                if abs(cx) < deadband and abs(cy) < deadband:
                    continue  # close enough: let the breathing motion do its thing
                now_yaw = float(present.get("head_yaw", self.yaw) or 0.0)
                now_pitch = float(present.get("head_pitch", self.pitch) or 0.0)
                target = (
                    now_yaw + float(self.cfg.get("yaw_sign", -1)) * cx * (hfov / 2) * gain,
                    now_pitch + float(self.cfg.get("pitch_sign", 1)) * cy * (vfov / 2) * gain,
                )
                if self.aim is None:
                    self.aim = target
                else:
                    self.aim = tuple(a * smooth + t * (1 - smooth) for a, t in zip(self.aim, target))
                if self.sent and max(abs(a - b) for a, b in zip(self.aim, self.sent)) < min_step:
                    continue
                self.yaw = max(-60.0, min(60.0, self.aim[0]))
                self.pitch = max(-40.0, min(30.0, self.aim[1]))
                self.sent = (self.yaw, self.pitch)
                await self.robot.post("/api/head/look_at", {"yaw": round(self.yaw, 1), "pitch": round(self.pitch, 1)})
            except RobotOffline:
                await asyncio.sleep(2)
            except Exception as exc:  # noqa: BLE001
                self.trace.emit("reflex", status="error", detail=f"tracking: {exc}")
                await asyncio.sleep(2)
