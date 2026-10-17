"""Ear servos and head lamp on the head Pi Zero 2 W.

Wiring (body_config.json, BCM numbering):
    left ear servo   GPIO 12 (pin 32)  hardware PWM0
    right ear servo  GPIO 13 (pin 33)  hardware PWM1
    head lamp        GPIO 26 (pin 37)  on/off, software-PWM dimming

Ears use the kernel PWM (dtoverlay=pwm-2chan,pin=12,func=4,pin2=13,func2=4),
so the pulses don't jitter while the eyes keep the CPU busy. Without the
overlay they fall back to lgpio's software servo pulses, and without any GPIO
access to a mock, so the service always starts.

Ear positions are -1..1 like Open Duck Mini's antennas.py (1.5 ms +- 0.5 ms):
0 = neutral, +1 = forward/up for both ears (each ear has its own sign). The
servos get no pulses until the first command, so starting the service never
moves anything.
"""

from __future__ import annotations

import json
import math
import random
import threading
import time
from pathlib import Path
from typing import Any, Optional

CONFIG_PATH = Path(__file__).with_name("body_config.json")

DEFAULT_CONFIG: dict[str, Any] = {
    "ears": {
        "left": {"gpio": 12, "pwm_channel": 0, "sign": 1, "trim": 0.0},
        "right": {"gpio": 13, "pwm_channel": 1, "sign": -1, "trim": 0.0},
        "pwm_chip": 0,
        "center_us": 1500,
        "range_us": 500,
        "limit": 0.9,
        "max_speed": 4.0,
        "follow_expressions": True,
        "release_after_s": 0,
    },
    "lamp": {"gpio": 26, "active_high": True, "pwm_hz": 200},
}

# Gestures as keyframes: (left, right, seconds to hold). None = keep current.
GESTURES: dict[str, list[tuple[Optional[float], Optional[float], float]]] = {
    "wiggle": [(0.6, -0.6, 0.18), (-0.6, 0.6, 0.18)],
    "perk": [(0.8, 0.8, 0.6)],
    "droop": [(-0.7, -0.7, 0.8)],
    "flick_left": [(0.8, None, 0.12), (0.0, None, 0.15)],
    "flick_right": [(None, 0.8, 0.12), (None, 0.0, 0.15)],
    "alert": [(0.9, 0.9, 0.25), (0.5, 0.5, 0.25)],
}
MAX_TIMES = 3


def load_config() -> dict[str, Any]:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if CONFIG_PATH.exists():
        user = json.loads(CONFIG_PATH.read_text())
        for section, values in user.items():
            if isinstance(values, dict) and isinstance(cfg.get(section), dict):
                for k, v in values.items():
                    if isinstance(v, dict) and isinstance(cfg[section].get(k), dict):
                        cfg[section][k].update(v)
                    else:
                        cfg[section][k] = v
            else:
                cfg[section] = values
    return cfg


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# ---------------------------------------------------------------- outputs


class SysfsServo:
    """One channel of the kernel PWM (pwm-2chan overlay)."""

    kind = "hw-pwm"
    PERIOD_NS = 20_000_000

    def __init__(self, chip: int, channel: int) -> None:
        self.base = Path(f"/sys/class/pwm/pwmchip{chip}")
        self.dir = self.base / f"pwm{channel}"
        if not self.base.exists():
            raise OSError(f"{self.base} missing (add dtoverlay=pwm-2chan to config.txt)")
        # Right after boot udev may still be handing the chip and the new channel
        # to the gpio group; wait up to ~5 s rather than falling back to software PWM.
        for _ in range(100):
            try:
                if not self.dir.exists():
                    (self.base / "export").write_text(str(channel))
                (self.dir / "period").write_text(str(self.PERIOD_NS))
                break
            except OSError:
                time.sleep(0.05)
        else:
            raise OSError(f"cannot write {self.dir}/period")
        self._enabled = False

    def pulse(self, us: Optional[float]) -> None:
        if us is None:
            if self._enabled:
                (self.dir / "enable").write_text("0")
                self._enabled = False
            return
        (self.dir / "duty_cycle").write_text(str(int(us * 1000)))
        if not self._enabled:
            (self.dir / "enable").write_text("1")
            self._enabled = True

    def close(self) -> None:
        self.pulse(None)


class LgpioServo:
    """Software servo pulses through lgpio (fallback without the overlay)."""

    kind = "sw-pwm"

    def __init__(self, handle: int, gpio: int) -> None:
        import lgpio  # noqa: PLC0415

        self.lg = lgpio
        self.h = handle
        self.gpio = gpio
        lgpio.gpio_claim_output(handle, gpio, 0)
        self._last: Optional[int] = None

    def pulse(self, us: Optional[float]) -> None:
        width = 0 if us is None else int(us)
        if width != self._last:
            self.lg.tx_servo(self.h, self.gpio, width, 50)
            self._last = width

    def close(self) -> None:
        self.pulse(None)
        self.lg.gpio_free(self.h, self.gpio)


class MockServo:
    kind = "mock"

    def __init__(self) -> None:
        self.us: Optional[float] = None

    def pulse(self, us: Optional[float]) -> None:
        self.us = us

    def close(self) -> None:
        pass


class LgpioLamp:
    kind = "gpio"

    def __init__(self, handle: int, gpio: int, active_high: bool, pwm_hz: int) -> None:
        import lgpio  # noqa: PLC0415

        self.lg = lgpio
        self.h = handle
        self.gpio = gpio
        self.active_high = active_high
        self.pwm_hz = pwm_hz
        lgpio.gpio_claim_output(handle, gpio, 0 if active_high else 1)
        self._pwm = False

    def set(self, brightness: float) -> None:
        if 0.0 < brightness < 1.0:
            duty = brightness if self.active_high else 1.0 - brightness
            self.lg.tx_pwm(self.h, self.gpio, self.pwm_hz, duty * 100.0)
            self._pwm = True
            return
        level = 1 if (brightness >= 1.0) == self.active_high else 0
        if self._pwm:
            # Re-claiming the pin is what reliably ends lgpio's software PWM.
            self.lg.gpio_free(self.h, self.gpio)
            self.lg.gpio_claim_output(self.h, self.gpio, level)
            self._pwm = False
        self.lg.gpio_write(self.h, self.gpio, level)

    def close(self) -> None:
        self.set(0.0)
        self.lg.gpio_free(self.h, self.gpio)


class MockLamp:
    kind = "mock"

    def set(self, brightness: float) -> None:
        pass

    def close(self) -> None:
        pass


def _open_lgpio() -> Optional[int]:
    try:
        import lgpio  # noqa: PLC0415

        return lgpio.gpiochip_open(0)
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------- ears


class Ears:
    """Eased ear motion, gestures and an optional idle twitch, in one thread."""

    def __init__(self, cfg: dict[str, Any], mock: bool, lg_handle: Optional[int]) -> None:
        self.cfg = cfg
        self.errors: list[str] = []
        self.servos = {side: self._open(side, mock, lg_handle) for side in ("left", "right")}
        self.kind = self.servos["left"].kind
        self.limit = float(cfg["limit"])

        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._pos = {"left": 0.0, "right": 0.0}
        self._target = {"left": 0.0, "right": 0.0}
        self._queue: list[tuple[Optional[float], Optional[float], float]] = []
        self._step_until = 0.0
        self._active = False  # no pulses until the first command
        self._last_move = 0.0
        self.idle = False
        self._next_twitch = 0.0
        self._thread = threading.Thread(target=self._run, name="ears", daemon=True)

    def _open(self, side: str, mock: bool, lg_handle: Optional[int]):
        ear = self.cfg[side]
        if not ear.get("enabled", True):
            # e.g. a 360-degree servo fitted by mistake: never drive it.
            self.errors.append(f"{side} ear disabled in body_config.json")
            return MockServo()
        if mock:
            return MockServo()
        try:
            return SysfsServo(int(self.cfg["pwm_chip"]), int(ear["pwm_channel"]))
        except OSError as exc:
            hw_err = str(exc)
        if lg_handle is not None:
            try:
                return LgpioServo(lg_handle, int(ear["gpio"]))
            except Exception as exc:  # noqa: BLE001
                self.errors.append(f"{side} ear: {hw_err}; lgpio: {exc}")
                return MockServo()
        self.errors.append(f"{side} ear: {hw_err}; no lgpio")
        return MockServo()

    # ------------------------------------------------------- commands

    def set(self, left: Optional[float], right: Optional[float]) -> dict[str, Any]:
        with self._lock:
            self._queue.clear()
            self._step_until = 0.0
            applied = self._apply_target(left, right)
            self._activate()
        reasons = [f"{side} ear {v:g} -> {applied[side]:g} (limit -{self.limit:g}..{self.limit:g})"
                   for side, v in (("left", left), ("right", right))
                   if v is not None and abs(applied[side] - float(v)) > 1e-9]
        return {"ok": True, "command": "ears", "applied": applied, "clamped": bool(reasons), "reasons": reasons}

    def gesture(self, name: str, times: int = 1) -> dict[str, Any]:
        if name not in GESTURES:
            raise KeyError(name)
        n = max(1, min(MAX_TIMES, int(times)))
        with self._lock:
            back = (self._target["left"], self._target["right"], 0.0)
            frames = GESTURES[name] * (n if name in ("wiggle", "alert") else 1)
            self._queue = list(frames)
            if name in ("wiggle", "alert", "flick_left", "flick_right"):
                self._queue.append(back)
            self._step_until = 0.0
            self._activate()
        reasons = [f"times {times} -> {n} (max {MAX_TIMES})"] if n != times else []
        return {"ok": True, "command": f"ears_{name}", "times": n, "clamped": bool(reasons), "reasons": reasons}

    def set_idle(self, enabled: bool) -> None:
        with self._lock:
            self.idle = enabled
            if enabled:
                self._activate()
                self._next_twitch = time.monotonic() + random.uniform(3, 8)

    def halt(self) -> None:
        with self._lock:
            self._queue.clear()
            self._target = dict(self._pos)
            self.idle = False

    def release(self) -> None:
        with self._lock:
            self._queue.clear()
            self.idle = False
            self._active = False
            for servo in self.servos.values():
                servo.pulse(None)

    def state(self) -> dict[str, Any]:
        with self._lock:
            return {
                "driver": self.kind,
                "active": self._active,
                "idle": self.idle,
                "position": {k: round(v, 3) for k, v in self._pos.items()},
                "target": {k: round(v, 3) for k, v in self._target.items()},
                "busy": bool(self._queue),
                "limit": self.limit,
                "gestures": list(GESTURES),
                "errors": self.errors,
            }

    def _apply_target(self, left: Optional[float], right: Optional[float]) -> dict[str, float]:
        for side, v in (("left", left), ("right", right)):
            if v is not None:
                self._target[side] = _clamp(float(v), -self.limit, self.limit)
        return dict(self._target)

    def _activate(self) -> None:
        if not self._active:
            self._active = True
            self._last_move = time.monotonic()

    # ------------------------------------------------------- loop

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1)
        for servo in self.servos.values():
            servo.close()

    def _run(self) -> None:
        period = 0.02
        last = time.monotonic()
        while not self._stop.is_set():
            now = time.monotonic()
            dt = min(0.1, now - last)
            last = now
            with self._lock:
                self._step(now, dt)
            self._stop.wait(period)

    def _step(self, now: float, dt: float) -> None:
        if self._queue and now >= self._step_until:
            left, right, hold = self._queue.pop(0)
            self._apply_target(left, right)
            self._step_until = now + hold
        elif not self._queue and self.idle and now >= self._next_twitch:
            # A small flick of one ear now and then, like a real animal.
            side = random.choice(("left", "right"))
            base = (self._target["left"], self._target["right"])
            kick = random.uniform(0.25, 0.45)
            flick = (base[0] + kick, None) if side == "left" else (None, base[1] + kick)
            self._queue = [(*flick, 0.12), (*base, 0.0)]
            self._next_twitch = now + random.uniform(4, 10)
        if not self._active:
            return
        max_step = float(self.cfg["max_speed"]) * dt
        moving = False
        for side in ("left", "right"):
            err = self._target[side] - self._pos[side]
            if abs(err) > 1e-4:
                moving = True
                self._pos[side] += _clamp(err, -max_step, max_step)
        if moving or self._queue:
            self._last_move = now
        release = float(self.cfg.get("release_after_s") or 0)
        # Holding still makes hobby servos hum; cut the pulses once the ear has
        # settled (the next move or twitch turns them back on).
        if release and now - self._last_move > release:
            for servo in self.servos.values():
                servo.pulse(None)
            return
        for side, servo in self.servos.items():
            ear = self.cfg[side]
            v = _clamp(self._pos[side] * float(ear["sign"]) + float(ear.get("trim", 0.0)), -1.0, 1.0)
            servo.pulse(float(self.cfg["center_us"]) + v * float(self.cfg["range_us"]))


# ---------------------------------------------------------------- lamp


class Lamp:
    def __init__(self, cfg: dict[str, Any], mock: bool, lg_handle: Optional[int]) -> None:
        self.error: Optional[str] = None
        self.dev: Any = MockLamp()
        if not mock:
            if lg_handle is None:
                self.error = "lgpio unavailable"
            else:
                try:
                    self.dev = LgpioLamp(lg_handle, int(cfg["gpio"]), bool(cfg["active_high"]), int(cfg["pwm_hz"]))
                except Exception as exc:  # noqa: BLE001
                    self.error = f"GPIO {cfg['gpio']}: {exc}"
        self.brightness = 0.0
        self._blink: Optional[threading.Thread] = None
        self._blink_stop = threading.Event()

    def set(self, on: Optional[bool], brightness: Optional[float]) -> dict[str, Any]:
        self._cancel_blink()
        if brightness is None:
            brightness = 1.0 if on else 0.0
        elif on is False:
            brightness = 0.0
        self._write(_clamp(float(brightness), 0.0, 1.0))
        return self.state()

    def blink(self, times: int, period_s: float = 0.4) -> dict[str, Any]:
        self._cancel_blink()
        n = max(1, min(5, int(times)))
        restore = self.brightness

        def run() -> None:
            for _ in range(n):
                self._write(0.0 if restore else 1.0)
                if self._blink_stop.wait(period_s / 2):
                    return
                self._write(restore if restore else 0.0)
                if self._blink_stop.wait(period_s / 2):
                    return

        self._blink_stop.clear()
        self._blink = threading.Thread(target=run, name="lamp-blink", daemon=True)
        self._blink.start()
        return {"ok": True, "times": n}

    def _cancel_blink(self) -> None:
        if self._blink and self._blink.is_alive():
            self._blink_stop.set()
            self._blink.join(timeout=1)

    def _write(self, brightness: float) -> None:
        self.dev.set(brightness)
        self.brightness = brightness

    def state(self) -> dict[str, Any]:
        return {"on": self.brightness > 0, "brightness": round(self.brightness, 3),
                "driver": self.dev.kind, "error": self.error}

    def close(self) -> None:
        self._cancel_blink()
        self.dev.close()


# ---------------------------------------------------------------- bundle


class Body:
    def __init__(self, mock: bool) -> None:
        self.cfg = load_config()
        self._lg = None if mock else _open_lgpio()
        self.ears = Ears(self.cfg["ears"], mock, self._lg)
        self.lamp = Lamp(self.cfg["lamp"], mock, self._lg)
        self.follow_expressions = bool(self.cfg["ears"].get("follow_expressions", True))

    def start(self) -> None:
        self.ears.start()

    def stop(self) -> None:
        self.ears.stop()
        self.lamp.close()
        if self._lg is not None:
            import lgpio  # noqa: PLC0415

            lgpio.gpiochip_close(self._lg)

    def on_expression(self, pose: Optional[list[float]]) -> None:
        """Ears follow the eyes' expression once they are in use."""
        if pose is None or not self.follow_expressions:
            return
        if self.ears.state()["active"] and not self.ears.state()["busy"]:
            self.ears.set(pose[0], pose[1])


def sine_test(ears: Ears, seconds: float = 4.0) -> None:
    """Gentle sweep, for checking the wiring by hand."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < seconds:
        v = 0.5 * math.sin(2 * math.pi * 0.5 * (time.monotonic() - t0))
        ears.set(v, v)
        time.sleep(0.05)
    ears.set(0, 0)
