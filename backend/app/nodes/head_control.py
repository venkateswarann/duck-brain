from __future__ import annotations

import asyncio
import json
import math
import os
import threading
import time
from collections import deque
from typing import Any, Optional

from ..runtime.base_node import Node
from ..runtime.bus import TelemetryBus
from ..runtime.locks import ResourceLocks
from ..schemas import DuckConfig, MotorTelemetry

HEAD_JOINTS = ("neck_pitch", "head_pitch", "head_yaw", "head_roll")
DEFAULT_IDS = {"neck_pitch": 30, "head_pitch": 31, "head_yaw": 32, "head_roll": 33}
# Calibration written by Open_Duck_Mini_Runtime (find_soft_offsets.py) lives here.
RUNTIME_CONFIG = os.path.expanduser("~/duck_config.json")
NOD_DEG = 12.0
SHAKE_DEG = 20.0
LOW_KP = 2


class HeadControlNode(Node):
    """Drives the head servos (IDs 30-33) for the companion mode.

    Every command is clamped to companion.head_limits, motion is speed-limited
    to max_vel_dps, commands are rate-limited, and gestures are capped. The
    legs are never written to. Clamps and rejections are logged and returned
    to the caller so the brain can show them.
    """

    id = "head.control"
    name = "Head Control"
    kind = "actuators.head"
    resources = ["serial"]
    topics_out = ["companion"]

    def __init__(self, bus: TelemetryBus, locks: ResourceLocks, config: DuckConfig) -> None:
        super().__init__(bus, locks)
        self.duck = config
        self.cfg = config.companion
        self.ids = {
            j: (config.joints[j].id if j in config.joints else DEFAULT_IDS[j]) for j in HEAD_JOINTS
        }
        self._io: Any = None
        self._mock = True
        self._lock = threading.Lock()
        self._stop_evt = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._cmd = {j: 0.0 for j in HEAD_JOINTS}  # degrees, what we send
        self._vel = {j: 0.0 for j in HEAD_JOINTS}  # deg/s of the smoothed motion
        # Breathing/sway layer. Off at boot (the head never moves by itself);
        # the brain or the Duck page turns it on.
        self._idle_on = False
        self._idle_gain = 0.0  # fades in/out so toggling never jumps
        self._idle_params = self.cfg.idle_motion.model_copy()
        self._t0 = time.monotonic()
        self._target = {j: 0.0 for j in HEAD_JOINTS}
        self._present: dict[str, Optional[float]] = {j: None for j in HEAD_JOINTS}
        self._queue: deque[tuple[dict[str, float], float]] = deque()  # (pose, dwell_s)
        self._dwell_until = 0.0
        self._last_cmd_at = time.monotonic()
        # The return-to-centre timeout only applies once something has moved the
        # head; at boot it must hold whatever pose it's in.
        self._commanded = False
        self.offsets: dict[str, float] = {}
        self.offsets_source = "none"
        self._tokens = self.cfg.cmd_rate_hz
        self._tokens_at = time.monotonic()
        self.events: deque[dict[str, Any]] = deque(maxlen=50)
        self._config = {"mock": True, "max_vel_dps": self.cfg.max_vel_dps, "control_hz": self.cfg.control_hz}

    # ------------------------------------------------------------ lifecycle

    async def on_start(self) -> None:
        self._mock = bool(self.duck.mock_hardware)
        self.offsets, self.offsets_source = self._load_offsets()
        if not self._mock and self.offsets_source == "none":
            self.log("ERROR no joint calibration found (DCS joints_offsets are all zero and "
                     f"{RUNTIME_CONFIG} has none): refusing to drive the head servos; running in MOCK mode")
            self._mock = True
        elif self.offsets_source != "none":
            self.log(f"head offsets from {self.offsets_source}: "
                     + ", ".join(f"{j}={self.offsets[j]:+.3f}" for j in HEAD_JOINTS))
        if not self._mock:
            try:
                await asyncio.to_thread(self._open_bus)
            except Exception as exc:  # noqa: BLE001
                self.log(f"rustypot unavailable or bus error ({exc}); head running in MOCK mode")
                self._io = None
                self._mock = True
        self._config["mock"] = self._mock
        self._config["offsets_source"] = self.offsets_source
        self._commanded = False
        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._control_loop, name="head-control", daemon=True)
        self._thread.start()
        self._task = asyncio.create_task(self._publish_loop(), name="head-publish")
        self.log(f"head control running ({'mock' if self._mock else 'servos'}) ids={self.ids}")

    def _open_bus(self) -> None:
        import rustypot  # type: ignore  # noqa: PLC0415

        io = rustypot.feetech(self.duck.serial_port, self.duck.baudrate)
        ids = list(self.ids.values())
        # Same soft start as mini_bdx_runtime HWI.turn_on, but only for the head
        # and starting from where the head already is, so nothing jumps.
        present = io.read_present_position(ids)
        io.set_kps(ids, [LOW_KP] * len(ids))
        io.write_goal_position(ids, present)
        time.sleep(0.5)
        io.set_kps(ids, [self.cfg.head_kp] * len(ids))
        for joint, rad in zip(self.ids, present):
            deg = math.degrees(rad - self._offset(joint))
            self._cmd[joint] = self._target[joint] = self._present[joint] = deg
        self.log("holding start pose (calibrated deg): "
                 + ", ".join(f"{j}={self._cmd[j]:+.1f}" for j in HEAD_JOINTS))
        self._io = io

    async def on_stop(self) -> None:
        self._stop_evt.set()
        if self._thread:
            await asyncio.to_thread(self._thread.join, 2.0)
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        # Torque stays on: the head holds its last pose instead of flopping.
        self._io = None

    def _offset(self, joint: str) -> float:
        return float(self.offsets.get(joint, 0.0))

    def _load_offsets(self) -> tuple[dict[str, float], str]:
        """Calibrated offsets (radians): DCS config first, else the runtime's ~/duck_config.json.

        All-zero offsets mean "never calibrated"; driving with them sends the head
        to the servos' raw zero, which is not the duck's home pose.
        """
        dcs = {j: float(self.duck.joints_offsets.get(j, 0.0)) for j in HEAD_JOINTS}
        if any(abs(v) > 1e-6 for v in dcs.values()):
            return dcs, "DCS config joints_offsets"
        try:
            with open(RUNTIME_CONFIG) as f:
                runtime = json.load(f).get("joints_offsets", {})
            rt = {j: float(runtime.get(j, 0.0)) for j in HEAD_JOINTS}
            if any(abs(v) > 1e-6 for v in rt.values()):
                return rt, RUNTIME_CONFIG
        except (OSError, ValueError):
            pass
        return dcs, "none"

    # ------------------------------------------------------------ commands

    def look_at(self, yaw: float, pitch: float, roll: Optional[float] = None) -> dict[str, Any]:
        pose = {"head_yaw": yaw, "head_pitch": pitch}
        if roll is not None:
            pose["head_roll"] = roll
        return self._command("look_at", pose)

    def tilt(self, angle: float) -> dict[str, Any]:
        return self._command("tilt", {"head_roll": angle})

    def center(self) -> dict[str, Any]:
        return self._command("center", {j: 0.0 for j in HEAD_JOINTS})

    def nod(self, times: int = 1) -> dict[str, Any]:
        return self._gesture("nod", "head_pitch", NOD_DEG, times)

    def shake(self, times: int = 1) -> dict[str, Any]:
        return self._gesture("shake", "head_yaw", SHAKE_DEG, times)

    def halt(self) -> dict[str, Any]:
        """Always accepted: drop queued motion and hold the current position.

        (Not named stop(): that's the Node lifecycle method.)"""
        with self._lock:
            self._queue.clear()
            self._idle_on = False
            self._idle_gain = 0.0
            for j in HEAD_JOINTS:
                self._target[j] = self._cmd[j]
                self._vel[j] = 0.0
            self._dwell_until = 0.0
        return self._result("stop", applied={k: round(v, 1) for k, v in self._cmd.items()})

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "mock": self._mock,
                "offsets_source": self.offsets_source,
                "running": self._thread is not None and self._thread.is_alive(),
                "command_deg": {k: round(v, 2) for k, v in self._cmd.items()},
                "target_deg": {k: round(v, 2) for k, v in self._target.items()},
                "present_deg": {k: (None if v is None else round(v, 2)) for k, v in self._present.items()},
                "queued": len(self._queue),
                "idle_motion": {"enabled": self._idle_on, **self._idle_params.model_dump()},
                "limits": {k: v.model_dump() for k, v in self.cfg.head_limits.items()},
                "recent_events": list(self.events)[-10:],
            }

    def _command(self, name: str, pose: dict[str, float]) -> dict[str, Any]:
        bad = [k for k, v in pose.items() if not _finite(v)]
        if bad:
            return self._reject(name, f"non-numeric value for {bad}")
        if not self._take_token():
            return self._reject(name, f"rate limit ({self.cfg.cmd_rate_hz:g}/s)")
        applied, clamped = self._clamp_pose(pose)
        with self._lock:
            self._queue.clear()
            self._target.update(applied)
            self._last_cmd_at = time.monotonic()
            self._commanded = True
        return self._result(name, applied=applied, clamped=clamped)

    def _gesture(self, name: str, joint: str, amp: float, times: Any) -> dict[str, Any]:
        if not _finite(times):
            return self._reject(name, "times must be a number")
        if not self._take_token():
            return self._reject(name, f"rate limit ({self.cfg.cmd_rate_hz:g}/s)")
        requested = int(times)
        n = max(1, min(requested, self.cfg.gesture_max_times))
        clamped = []
        if n != requested:
            clamped.append(f"times {requested} -> {n} (max {self.cfg.gesture_max_times})")
        with self._lock:
            base = dict(self._target)
            self._queue.clear()
            for _ in range(n):
                for sign in (1, -1):
                    pose, c = self._clamp_pose({joint: base[joint] + sign * amp})
                    self._queue.append(({**base, **pose}, 0.05))
                    clamped.extend(x for x in c if x not in clamped)
            self._queue.append((base, 0.0))
            self._last_cmd_at = time.monotonic()
            self._commanded = True
        return self._result(name, applied={"times": n, "joint": joint, "amplitude_deg": amp}, clamped=clamped)

    def _clamp_pose(self, pose: dict[str, float]) -> tuple[dict[str, float], list[str]]:
        applied: dict[str, float] = {}
        clamped: list[str] = []
        for joint, value in pose.items():
            lim = self.cfg.head_limits.get(joint)
            v = float(value)
            if lim is not None:
                c = min(max(v, lim.min_deg), lim.max_deg)
                if abs(c - v) > 1e-6:
                    clamped.append(f"{joint} {v:g} -> {c:g} deg (limit {lim.min_deg:g}..{lim.max_deg:g})")
                v = c
            applied[joint] = round(v, 2)
        return applied, clamped

    def _take_token(self) -> bool:
        now = time.monotonic()
        rate = max(0.1, self.cfg.cmd_rate_hz)
        self._tokens = min(rate, self._tokens + (now - self._tokens_at) * rate)
        self._tokens_at = now
        if self._tokens < 1.0:
            return False
        self._tokens -= 1.0
        return True

    def _result(self, name: str, applied: Any = None, clamped: Optional[list[str]] = None) -> dict[str, Any]:
        clamped = clamped or []
        res = {"ok": True, "command": name, "applied": applied, "clamped": bool(clamped), "reasons": clamped}
        if clamped:
            self.log(f"CLAMP {name}: {'; '.join(clamped)}")
            self.events.append({"ts": time.time(), "kind": "clamp", "command": name, "reasons": clamped})
        return res

    def _reject(self, name: str, reason: str) -> dict[str, Any]:
        self.log(f"REJECT {name}: {reason}")
        self.events.append({"ts": time.time(), "kind": "reject", "command": name, "reasons": [reason]})
        return {"ok": False, "command": name, "applied": None, "clamped": False, "reasons": [reason]}

    # ------------------------------------------------------------ loops

    def _control_loop(self) -> None:
        dt = 1.0 / max(5.0, self.cfg.control_hz)
        tick = 0
        while not self._stop_evt.is_set():
            started = time.monotonic()
            with self._lock:
                self._advance(dt, started)
                cmd = dict(self._cmd)
            if self._io is not None:
                try:
                    ids = [self.ids[j] for j in HEAD_JOINTS]
                    self._io.write_goal_position(
                        ids, [math.radians(cmd[j]) + self._offset(j) for j in HEAD_JOINTS]
                    )
                    if tick % 5 == 0:  # ~10 Hz read-back for telemetry
                        rads = self._io.read_present_position(ids)
                        with self._lock:
                            for j, r in zip(HEAD_JOINTS, rads):
                                self._present[j] = math.degrees(r - self._offset(j))
                except Exception as exc:  # noqa: BLE001
                    self.log(f"bus error: {exc}")
            else:
                with self._lock:
                    self._present.update(cmd)
            tick += 1
            self._stop_evt.wait(max(0.0, dt - (time.monotonic() - started)))

    def _advance(self, dt: float, now: float) -> None:
        """Move _cmd toward _target at <= max_vel_dps; feed gestures; enforce hold timeout."""
        if self._queue and now >= self._dwell_until and self._at_target():
            pose, dwell = self._queue.popleft()
            self._target.update(pose)
            self._dwell_until = now + dwell
        if (
            self._commanded
            and not self._queue
            and now - self._last_cmd_at > self.cfg.hold_timeout_s
            and any(abs(v) > 0.5 for v in self._target.values())
        ):
            self.log(f"hold timeout ({self.cfg.hold_timeout_s:g}s): returning to centre")
            self.events.append({"ts": time.time(), "kind": "timeout", "command": "hold", "reasons": ["returned to centre"]})
            self._target = {j: 0.0 for j in HEAD_JOINTS}
            self._last_cmd_at = now
        # Breathing fades in when enabled and drops to a third during gestures.
        want = (0.35 if self._queue else 1.0) if self._idle_on else 0.0
        self._idle_gain += (want - self._idle_gain) * min(1.0, dt / 1.5)
        offsets = self._idle_offsets(now - self._t0)

        # Critically damped spring toward target + breathing, with acceleration
        # and speed caps: every move eases in and out, and a new target mid-move
        # bends the path instead of restarting it.
        w = 4.0 / max(0.1, self.cfg.response_s)
        amax = self.cfg.max_acc_dps2
        vmax = self.cfg.max_vel_dps
        for j in HEAD_JOINTS:
            desired = self._clamp_joint(j, self._target[j] + offsets.get(j, 0.0) * self._idle_gain)
            acc = w * w * (desired - self._cmd[j]) - 2.0 * w * self._vel[j]
            acc = max(-amax, min(amax, acc))
            self._vel[j] = max(-vmax, min(vmax, self._vel[j] + acc * dt))
            self._cmd[j] = self._clamp_joint(j, self._cmd[j] + self._vel[j] * dt)

    def _idle_offsets(self, t: float) -> dict[str, float]:
        """Slow breath on pitch plus an aperiodic sway (sum of incommensurate sines)."""
        p = self._idle_params
        tau = 2 * math.pi
        breath = p.breath_deg * math.sin(tau * p.breath_hz * t)
        sway = p.sway_deg * (0.6 * math.sin(tau * 0.047 * t) + 0.4 * math.sin(tau * 0.113 * t + 1.3))
        roll = 0.5 * p.sway_deg * math.sin(tau * 0.071 * t + 2.1)
        return {"head_pitch": breath, "head_yaw": sway, "head_roll": roll}

    def _clamp_joint(self, joint: str, value: float) -> float:
        lim = self.cfg.head_limits.get(joint)
        return value if lim is None else min(max(value, lim.min_deg), lim.max_deg)

    def set_idle_motion(self, enabled: bool, breath_deg: Optional[float] = None,
                        sway_deg: Optional[float] = None) -> dict[str, Any]:
        """Turn the breathing/sway layer on or off (amplitudes capped at 4 degrees)."""
        clamped = []
        with self._lock:
            for name, value in (("breath_deg", breath_deg), ("sway_deg", sway_deg)):
                if value is None:
                    continue
                if not _finite(value):
                    return self._reject("idle_motion", f"{name} must be a number")
                c = min(max(float(value), 0.0), 4.0)
                if c != float(value):
                    clamped.append(f"{name} {value} -> {c:g} (max 4)")
                setattr(self._idle_params, name, c)
            self._idle_on = bool(enabled)
        return self._result("idle_motion", applied={"enabled": self._idle_on, **self._idle_params.model_dump()},
                            clamped=clamped)

    def _at_target(self) -> bool:
        # Gestures advance once the smoothed motion is close and has nearly stopped.
        return all(abs(self._target[j] - self._cmd[j]) < 1.5 and abs(self._vel[j]) < 25
                   for j in HEAD_JOINTS)

    async def _publish_loop(self) -> None:
        while True:
            st = self.snapshot()
            motors = {}
            for j in HEAD_JOINTS:
                deg = st["present_deg"][j]
                if deg is None:
                    continue
                motors[j] = MotorTelemetry(
                    id=self.ids[j], name=j, position=round(math.radians(deg), 4)
                ).model_dump()
            await self.bus.update(companion={"head": st}, motors=motors)
            await asyncio.sleep(0.2)


def _finite(v: Any) -> bool:
    try:
        return math.isfinite(float(v))
    except (TypeError, ValueError):
        return False
