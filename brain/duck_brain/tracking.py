"""Fast reflex loop: follow faces with the eyes and head, no LLM involved.

Frames come from the robot's live MJPEG stream (a background reader keeps only
the newest JPEG), so there's no per-frame request delay. Faces are found with
OpenCV's YuNet detector (robust to turned heads and poor light), falling back to
a Haar cascade if the model file is missing.

The camera sits in the duck's head, so a face's pixel offset is an angle
relative to where the head points *now*. Each frame we read the head's measured
angle, add the face's offset to get where the face actually is, smooth that aim
point, and send it as an absolute target; the robot's spring-damper motion
blends the updates into one glide. The eyes jump to the face first and the head
follows. A few missed detections don't count as the person leaving.

Reactions make it playful: a new face gets starstruck eyes, leaning in very
close makes it go cross-eyed, leaving makes it look around, and now and then it
winks or bounces its eyes at whoever is there.
"""

from __future__ import annotations

import asyncio
import random
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import cv2
import httpx
import numpy as np

from .robot import Robot, RobotOffline
from .trace import Trace

YUNET_MODEL = Path(__file__).with_name("models") / "face_detection_yunet_2023mar.onnx"


class FrameGrabber:
    """Keeps the newest JPEG from the robot's MJPEG stream."""

    def __init__(self, robot: Robot, stream: str) -> None:
        self.robot = robot
        self.stream = stream
        self.jpeg: Optional[bytes] = None
        self.seq = 0
        self.at = 0.0

    async def run(self) -> None:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=5.0)) as http:
            while True:
                base = self.robot.base or await self.robot.discover()
                if not base:
                    await asyncio.sleep(2)
                    continue
                try:
                    async with http.stream("GET", f"{base}/stream/video/{self.stream}") as r:
                        if r.status_code != 200:
                            await asyncio.sleep(2)
                            continue
                        buf = bytearray()
                        async for chunk in r.aiter_bytes():
                            buf += chunk
                            end = buf.rfind(b"\xff\xd9")
                            if end < 0:
                                if len(buf) > 2_000_000:
                                    buf.clear()
                                continue
                            start = buf.rfind(b"\xff\xd8", 0, end)
                            if start >= 0:
                                self.jpeg = bytes(buf[start:end + 2])
                                self.seq += 1
                                self.at = time.monotonic()
                            del buf[:end + 2]
                except (httpx.HTTPError, OSError):
                    pass
                await asyncio.sleep(1)


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
        self.grabber = FrameGrabber(robot, stream)
        self.yunet = None
        if YUNET_MODEL.exists() and hasattr(cv2, "FaceDetectorYN"):
            self.yunet = cv2.FaceDetectorYN.create(str(YUNET_MODEL), "", (320, 240),
                                                   float(cfg.get("min_confidence", 0.7)), 0.3, 20)
        self.haar = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        self.yaw = 0.0
        self.pitch = 0.0
        self.aim: Optional[tuple[float, float]] = None  # smoothed absolute face direction
        self.sent: Optional[tuple[float, float]] = None
        self.sent_at = 0.0
        self.eyes_sent: Optional[tuple[float, float]] = None
        self.eyes_at = 0.0
        self.last_seen = 0.0
        self.face_present = False
        self.centred_after_loss = True
        self.close_since: Optional[float] = None
        self.next_react = {"close": 0.0, "idle": time.monotonic() + 20, "lost": 0.0}
        self.hits = 0  # consecutive frames with a face

    def pause(self, seconds: float) -> None:
        self.paused_until = max(self.paused_until, time.monotonic() + seconds)

    def sync_pose(self, yaw: float, pitch: float) -> None:
        self.yaw, self.pitch = yaw, pitch
        self.aim = self.sent = None

    @property
    def detector_name(self) -> str:
        return "yunet" if self.yunet is not None else "haar"

    def detect(self, jpeg: bytes) -> Optional[tuple[float, float, float]]:
        """Largest face as (x, y, size), x/y normalised to -1..1 from the image centre."""
        img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return None
        h, w = img.shape[:2]
        scale = 320 / w if w > 320 else 1.0
        small = cv2.resize(img, (int(w * scale), int(h * scale))) if scale != 1.0 else img
        sh, sw = small.shape[:2]
        if self.yunet is not None:
            self.yunet.setInputSize((sw, sh))
            _, faces = self.yunet.detect(small)
            if faces is None or len(faces) == 0:
                return None
            x, y, fw, fh = max(faces, key=lambda f: f[2] * f[3])[:4]
        else:
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            found = self.haar.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=5, minSize=(28, 28))
            if len(found) == 0:
                return None
            x, y, fw, fh = max(found, key=lambda f: f[2] * f[3])
        cx = (x + fw / 2) / sw * 2 - 1
        cy = (y + fh / 2) / sh * 2 - 1
        return float(cx), float(cy), float(fw / sw)

    # ------------------------------------------------------------ reactions

    async def _eyes(self, path: str, body: dict[str, Any]) -> None:
        try:
            await self.robot.post(path, body)
        except Exception:  # noqa: BLE001  (reactions are best effort)
            pass

    def _react(self, path: str, body: dict[str, Any], why: str) -> None:
        if not self.cfg.get("reactions", True):
            return
        self.trace.emit("reflex", detail=why)
        asyncio.create_task(self._eyes(path, body))

    # ------------------------------------------------------------ loop

    async def run(self) -> None:
        grab = asyncio.create_task(self.grabber.run(), name="camera-stream")
        try:
            await self._loop()
        finally:
            grab.cancel()

    async def _loop(self) -> None:
        period = 1.0 / float(self.cfg.get("rate_hz", 12))
        hfov = float(self.cfg.get("horizontal_fov_deg", 62))
        vfov = float(self.cfg.get("vertical_fov_deg", 48))
        gain = float(self.cfg.get("gain", 0.7))
        deadband = float(self.cfg.get("deadband", 0.06))
        smooth = float(self.cfg.get("smoothing", 0.35))  # 0 = raw, closer to 1 = smoother/slower
        min_step = float(self.cfg.get("min_step_deg", 0.4))
        head_interval = 1.0 / float(self.cfg.get("head_rate_hz", 8))  # stay under DCS's command rate limit
        lost_after = float(self.cfg.get("lost_after_s", 1.2))
        greet_gap = float(self.cfg.get("greet_after_absent_s", 20))
        center_after = float(self.cfg.get("center_after_lost_s", 8))
        close_size = float(self.cfg.get("close_face_size", 0.45))
        last_seq = 0
        announced = False
        while True:
            await asyncio.sleep(period)
            if not self.enabled or time.monotonic() < self.paused_until:
                continue
            if not announced:
                announced = True
                self.trace.emit("reflex", detail=f"face tracking: {self.detector_name} on the live camera stream")
            try:
                if self.grabber.seq == last_seq or time.monotonic() - self.grabber.at > 2.0:
                    continue  # no new (or no fresh) frame
                last_seq = self.grabber.seq
                jpeg = self.grabber.jpeg
                head_task = asyncio.create_task(self.robot.get("/api/head/state"))
                face = await asyncio.to_thread(self.detect, jpeg)
                now = time.monotonic()
                if face is None:
                    head_task.cancel()
                    self.hits = 0
                    if self.face_present and now - self.last_seen > lost_after:
                        self.face_present = False
                        self.close_since = None
                        self.trace.set_state(face=False)
                        if now >= self.next_react["lost"]:
                            self.next_react["lost"] = now + 20
                            self._react("/api/eyes/action", {"name": "look_around"}, "face lost: looking around")
                    if not self.centred_after_loss and now - self.last_seen > center_after:
                        self.centred_after_loss = True
                        self.yaw = self.pitch = 0.0
                        self.aim = self.sent = None
                        await self.robot.post("/api/head/center")
                    continue

                cx, cy, size = face
                self.hits += 1
                if not self.face_present and self.hits < 2:
                    head_task.cancel()
                    continue  # one stray detection isn't a person yet
                if not self.face_present:
                    absent_for = now - self.last_seen if self.last_seen else 1e9
                    self.face_present = True
                    self.trace.set_state(face=True)
                    if absent_for > greet_gap:
                        self._react("/api/eyes/expression", {"name": "starstruck", "hold_s": 2},
                                    "new face: starstruck")
                        if self.cfg.get("greet_on_face", True):
                            self.trace.emit("reflex", detail="new face in view")
                            asyncio.create_task(self.on_new_face())
                self.last_seen = now
                self.centred_after_loss = False

                # Leaning right in makes the duck go cross-eyed.
                if size >= close_size:
                    self.close_since = self.close_since or now
                    if now - self.close_since > 0.6 and now >= self.next_react["close"]:
                        self.next_react["close"] = now + 15
                        self._react("/api/eyes/action", {"name": "cross_eyes"}, "face very close: cross-eyed")
                else:
                    self.close_since = None
                # Now and then, a wink or a happy bounce for whoever is there.
                if now >= self.next_react["idle"]:
                    self.next_react["idle"] = now + random.uniform(25, 45)
                    act = random.choice(["wink", "happy_bounce", "double_blink"])
                    self._react("/api/eyes/action", {"name": act}, f"playful: {act}")

                # Eyes: quick correction toward the face (only when it moved).
                ex = max(-1.0, min(1.0, cx * float(self.cfg.get("eyes_x_sign", 1))))
                ey = max(-1.0, min(1.0, cy))
                if (self.eyes_sent is None or max(abs(ex - self.eyes_sent[0]), abs(ey - self.eyes_sent[1])) > 0.06
                        or now - self.eyes_at > 1.0):
                    self.eyes_sent, self.eyes_at = (ex, ey), now
                    asyncio.create_task(self._eyes("/api/eyes/look", {"x": round(ex, 2), "y": round(ey, 2), "hold_s": 2}))

                try:
                    head = await head_task
                except Exception:  # noqa: BLE001
                    head = {}
                present = head.get("present_deg", {}) if isinstance(head, dict) else {}

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
                if now - self.sent_at < head_interval:
                    continue
                self.yaw = max(-60.0, min(60.0, self.aim[0]))
                self.pitch = max(-40.0, min(30.0, self.aim[1]))
                self.sent, self.sent_at = (self.yaw, self.pitch), now
                await self.robot.post("/api/head/look_at", {"yaw": round(self.yaw, 1), "pitch": round(self.pitch, 1)})
            except RobotOffline:
                await asyncio.sleep(2)
            except Exception as exc:  # noqa: BLE001
                self.trace.emit("reflex", status="error", detail=f"tracking: {exc}")
                await asyncio.sleep(2)
