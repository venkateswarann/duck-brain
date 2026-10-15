"""Animation loop for the eyes, driven by commands instead of random choices.

emo1.py picked a random emotion every few seconds. Here the expression and
gaze come from the API; when nobody has commanded the gaze for a while the
eyes fall back to idle saccades, and blinks keep happening on their own.
"""

from __future__ import annotations

import math
import random
import threading
import time
from typing import Any, Optional

from eye_renderer import LID_KEYS, MAX_OFFSET, DualDisplay, draw_eye

EASE_FACTOR = 0.15
EMOTION_EASE = 0.1
BLINK_FRAMES = (0.3, 0.7, 1.0, 0.6, 0.2, 0.0)


class EyeEngine:
    def __init__(
        self,
        display: DualDisplay,
        expressions: dict[str, dict[str, Any]],
        fps: float = 30.0,
        idle_after_s: float = 4.0,
    ) -> None:
        self.display = display
        self.expressions = expressions
        self.fps = fps
        self.idle_after_s = idle_after_s

        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self.expression = "neutral"
        self._expression_until: Optional[float] = None
        self._state = {k: float(expressions["neutral"][k]) for k in LID_KEYS}
        self._gaze_target = (0.0, 0.0)  # normalised -1..1
        self._gaze = (0.0, 0.0)
        self._manual_until = 0.0
        self.idle_enabled = True
        self._blink_requested = False
        self._next_idle_move = 0.0
        self._next_blink = time.monotonic() + random.uniform(2, 5)

        self.frames = 0
        self.last_frame_ms = 0.0
        self._latest: Optional[tuple[Any, Any]] = None

    # ----------------------------------------------------------- commands

    def set_expression(self, name: str, hold_s: Optional[float] = None) -> None:
        if name not in self.expressions:
            raise KeyError(name)
        with self._lock:
            self.expression = name
            self._expression_until = time.monotonic() + hold_s if hold_s else None
            bias = self.expressions[name].get("gaze")
            if bias is not None:
                self._gaze_target = _clamp_unit(bias[0], bias[1])
                self._manual_until = time.monotonic() + max(self.idle_after_s, hold_s or 0)

    def look(self, x: float, y: float, hold_s: Optional[float] = None) -> tuple[float, float]:
        with self._lock:
            self._gaze_target = _clamp_unit(x, y)
            self._manual_until = time.monotonic() + (hold_s or self.idle_after_s)
            return self._gaze_target

    def blink(self) -> None:
        with self._lock:
            self._blink_requested = True

    def set_idle(self, enabled: bool) -> None:
        with self._lock:
            self.idle_enabled = enabled

    def state(self) -> dict[str, Any]:
        with self._lock:
            return {
                "expression": self.expression,
                "gaze": {"x": round(self._gaze[0], 3), "y": round(self._gaze[1], 3)},
                "gaze_target": {"x": self._gaze_target[0], "y": self._gaze_target[1]},
                "idle": self.idle_enabled and time.monotonic() >= self._manual_until,
                "frames": self.frames,
                "frame_ms": round(self.last_frame_ms, 1),
                "fps_cap": self.fps,
            }

    def latest_images(self) -> Optional[tuple[Any, Any]]:
        return self._latest

    # ----------------------------------------------------------- loop

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="eye-engine", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self.display.cleanup()

    def _run(self) -> None:
        period = 1.0 / self.fps
        while not self._stop.is_set():
            started = time.monotonic()
            blink = self._tick(started)
            if blink:
                for factor in BLINK_FRAMES:
                    self._render(factor)
            else:
                self._render(0.0)
            self.last_frame_ms = (time.monotonic() - started) * 1000
            delay = period - (time.monotonic() - started)
            if delay > 0:
                self._stop.wait(delay)

    def _tick(self, now: float) -> bool:
        with self._lock:
            if self._expression_until and now >= self._expression_until:
                self.expression = "neutral"
                self._expression_until = None

            if now >= self._manual_until and self.idle_enabled and now >= self._next_idle_move:
                angle = random.uniform(0, 2 * math.pi)
                dist = random.uniform(0, 1)
                self._gaze_target = (dist * math.cos(angle), dist * math.sin(angle))
                self._next_idle_move = now + random.uniform(0.6, 2.5)

            gx, gy = self._gaze
            tx, ty = self._gaze_target
            self._gaze = (gx + (tx - gx) * EASE_FACTOR, gy + (ty - gy) * EASE_FACTOR)

            target = self.expressions[self.expression]
            for key in LID_KEYS:
                self._state[key] += (float(target[key]) - self._state[key]) * EMOTION_EASE

            blink = self._blink_requested or now >= self._next_blink
            if blink:
                self._blink_requested = False
                self._next_blink = now + random.uniform(2.0, 6.0)
            return blink

    def _render(self, blink_factor: float) -> None:
        with self._lock:
            ox = self._gaze[0] * MAX_OFFSET
            oy = self._gaze[1] * MAX_OFFSET
            state = dict(self._state)
        left = draw_eye(ox, oy, state, blink_factor, is_left=True)
        right = draw_eye(ox, oy, state, blink_factor, is_left=False)
        self.display.show(left, right)
        self._latest = (left, right)
        self.frames += 1


def _clamp_unit(x: float, y: float) -> tuple[float, float]:
    """Keep the gaze inside the unit circle so the iris never leaves the sclera."""
    x, y = float(x), float(y)
    mag = math.hypot(x, y)
    if mag > 1.0:
        x, y = x / mag, y / mag
    return x, y
