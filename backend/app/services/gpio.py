"""GPIO service — wraps RPi.GPIO with mock fallback.

Provides pin setup, digital read/write, software PWM, and continuous
probing that publishes samples to the TelemetryBus.
"""
from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

# RPi.GPIO is optional — only present on actual Raspberry Pi hardware.
try:
    import RPi.GPIO as _GPIO  # type: ignore[import-untyped]

    _HAS_GPIO = True
except ImportError:
    _GPIO = None  # type: ignore[assignment]
    _HAS_GPIO = False


class Direction(str, Enum):
    IN = "IN"
    OUT = "OUT"


class Pull(str, Enum):
    UP = "UP"
    DOWN = "DOWN"
    NONE = "NONE"


@dataclass
class PinState:
    bcm: int
    direction: Direction
    pull: Pull = Pull.NONE
    value: int = 0
    pwm_freq: float = 0.0
    pwm_duty: float = 0.0
    is_pwm: bool = False
    probing: bool = False
    probe_rate_hz: float = 50.0
    device_id: Optional[str] = None
    label: Optional[str] = None


@dataclass
class ProbeTask:
    bcm: int
    rate_hz: float
    task: Optional[asyncio.Task] = None


class GpioService:
    """Manages GPIO pins with RPi.GPIO or mock mode."""

    def __init__(
        self,
        mock: bool = True,
        bus: Any = None,
        node_id: str = "gpio.pins",
    ) -> None:
        self.mock = mock or not _HAS_GPIO
        self.bus = bus
        self.node_id = node_id
        self._pins: dict[int, PinState] = {}
        self._pwm_handles: dict[int, Any] = {}
        self._probes: dict[int, ProbeTask] = {}
        self._mock_values: dict[int, int] = {}
        self._initialised = False

    def init_hardware(self) -> None:
        """Set BCM mode on real hardware."""
        if self._initialised:
            return
        if not self.mock:
            _GPIO.setmode(_GPIO.BCM)
            _GPIO.setwarnings(False)
        self._initialised = True

    def _log(self, msg: str) -> None:
        if self.bus:
            self.bus.append_log(self.node_id, msg)

    # ── Pin setup ──────────────────────────────────────────────────

    def setup_pin(
        self,
        bcm: int,
        direction: Direction,
        pull: Pull = Pull.NONE,
        device_id: str | None = None,
        label: str | None = None,
    ) -> PinState:
        self.init_hardware()
        if not self.mock:
            pull_map = {
                Pull.UP: _GPIO.PUD_UP,
                Pull.DOWN: _GPIO.PUD_DOWN,
                Pull.NONE: _GPIO.PUD_OFF,
            }
            if direction == Direction.IN:
                _GPIO.setup(bcm, _GPIO.IN, pull_up_down=pull_map.get(pull, _GPIO.PUD_OFF))
            else:
                _GPIO.setup(bcm, _GPIO.OUT, initial=_GPIO.LOW)

        state = PinState(
            bcm=bcm,
            direction=direction,
            pull=pull,
            device_id=device_id,
            label=label,
        )
        self._pins[bcm] = state
        self._mock_values[bcm] = 0
        self._log(f"BCM{bcm} setup as {direction.value}"
                  f"{f' pull={pull.value}' if pull != Pull.NONE else ''}"
                  f"{f' ({label})' if label else ''}")
        return state

    # ── Digital write / read ───────────────────────────────────────

    def write_pin(self, bcm: int, value: int) -> int:
        pin = self._pins.get(bcm)
        if pin is None:
            raise ValueError(f"BCM{bcm} not set up")
        if pin.direction != Direction.OUT:
            raise ValueError(f"BCM{bcm} is {pin.direction.value}, cannot write")

        clamped = 1 if value else 0
        if not self.mock:
            _GPIO.output(bcm, clamped)
        pin.value = clamped
        self._mock_values[bcm] = clamped
        self._log(f"BCM{bcm} → {'HIGH' if clamped else 'LOW'}"
                  f"{f' ({pin.label})' if pin.label else ''}")
        return clamped

    def read_pin(self, bcm: int) -> int:
        pin = self._pins.get(bcm)
        if pin is None:
            raise ValueError(f"BCM{bcm} not set up")

        if self.mock:
            if pin.direction == Direction.IN:
                # Simulate noisy digital input
                self._mock_values[bcm] = random.choice([0, 0, 0, 1])
            val = self._mock_values.get(bcm, 0)
        else:
            val = _GPIO.input(bcm)
        pin.value = val
        return val

    # ── PWM ────────────────────────────────────────────────────────

    def set_pwm(self, bcm: int, frequency: float, duty_cycle: float) -> None:
        pin = self._pins.get(bcm)
        if pin is None:
            raise ValueError(f"BCM{bcm} not set up")

        duty_cycle = max(0.0, min(100.0, duty_cycle))
        frequency = max(1.0, frequency)

        if not self.mock:
            if bcm in self._pwm_handles:
                pwm = self._pwm_handles[bcm]
                pwm.ChangeFrequency(frequency)
                pwm.ChangeDutyCycle(duty_cycle)
            else:
                if pin.direction != Direction.OUT:
                    _GPIO.setup(bcm, _GPIO.OUT)
                    pin.direction = Direction.OUT
                pwm = _GPIO.PWM(bcm, frequency)
                pwm.start(duty_cycle)
                self._pwm_handles[bcm] = pwm

        pin.is_pwm = True
        pin.pwm_freq = frequency
        pin.pwm_duty = duty_cycle
        self._log(f"BCM{bcm} PWM {frequency}Hz duty={duty_cycle:.1f}%"
                  f"{f' ({pin.label})' if pin.label else ''}")

    def stop_pwm(self, bcm: int) -> None:
        pin = self._pins.get(bcm)
        if pin and pin.is_pwm:
            if bcm in self._pwm_handles:
                self._pwm_handles[bcm].stop()
                del self._pwm_handles[bcm]
            pin.is_pwm = False
            pin.pwm_freq = 0
            pin.pwm_duty = 0
            self._log(f"BCM{bcm} PWM stopped")

    # ── Probing (continuous read) ──────────────────────────────────

    async def start_probe(self, bcm: int, rate_hz: float = 50.0) -> None:
        pin = self._pins.get(bcm)
        if pin is None:
            raise ValueError(f"BCM{bcm} not set up")

        if bcm in self._probes and self._probes[bcm].task is not None:
            return  # already probing

        pin.probing = True
        pin.probe_rate_hz = rate_hz
        probe = ProbeTask(bcm=bcm, rate_hz=rate_hz)
        probe.task = asyncio.create_task(self._probe_loop(bcm, rate_hz))
        self._probes[bcm] = probe
        self._log(f"BCM{bcm} probe started at {rate_hz}Hz"
                  f"{f' ({pin.label})' if pin.label else ''}")

    async def stop_probe(self, bcm: int) -> None:
        probe = self._probes.pop(bcm, None)
        if probe and probe.task:
            probe.task.cancel()
            try:
                await probe.task
            except asyncio.CancelledError:
                pass
        pin = self._pins.get(bcm)
        if pin:
            pin.probing = False
        self._log(f"BCM{bcm} probe stopped")

    async def _probe_loop(self, bcm: int, rate_hz: float) -> None:
        interval = 1.0 / max(1.0, rate_hz)
        try:
            while True:
                val = self.read_pin(bcm)
                if self.bus:
                    # Publish to telemetry bus under gpio section
                    await self.bus.update(
                        gpio={f"bcm{bcm}": {"value": val, "ts": time.time()}}
                    )
                    # Also fan out a dedicated probe event for the WebSocket
                    await self.bus.publish_event({
                        "type": "gpio_probe",
                        "bcm": bcm,
                        "value": val,
                        "ts": time.time(),
                    })
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass

    # ── Cleanup ────────────────────────────────────────────────────

    def cleanup_pin(self, bcm: int) -> None:
        self.stop_pwm(bcm)
        probe = self._probes.pop(bcm, None)
        if probe and probe.task:
            probe.task.cancel()
        if not self.mock and bcm in self._pins:
            _GPIO.cleanup(bcm)
        self._pins.pop(bcm, None)
        self._mock_values.pop(bcm, None)
        self._log(f"BCM{bcm} released")

    def cleanup_all(self) -> None:
        for bcm in list(self._pins):
            self.stop_pwm(bcm)
        for bcm, probe in list(self._probes.items()):
            if probe.task:
                probe.task.cancel()
        self._probes.clear()
        if not self.mock and self._initialised:
            _GPIO.cleanup()
        self._pins.clear()
        self._mock_values.clear()
        self._initialised = False
        self._log("all GPIO released")

    # ── State query ────────────────────────────────────────────────

    def get_state(self) -> list[dict[str, Any]]:
        out = []
        for bcm, pin in sorted(self._pins.items()):
            out.append({
                "bcm": bcm,
                "direction": pin.direction.value,
                "pull": pin.pull.value,
                "value": pin.value,
                "is_pwm": pin.is_pwm,
                "pwm_freq": pin.pwm_freq,
                "pwm_duty": pin.pwm_duty,
                "probing": pin.probing,
                "probe_rate_hz": pin.probe_rate_hz,
                "device_id": pin.device_id,
                "label": pin.label,
            })
        return out

    @property
    def is_mock(self) -> bool:
        return self.mock
