from __future__ import annotations

import asyncio
import math
import time
from typing import Any, Optional

from ..runtime.base_node import Node
from ..runtime.bus import TelemetryBus
from ..runtime.locks import ResourceLocks
from ..schemas import DuckConfig, MotorTelemetry, NodeState


def _steps_to_rad(steps: int) -> float:
    # STS3215: 4096 steps ≈ 2π
    return (steps - 2048) * (2 * math.pi / 4096)


class MotorsTelemetryNode(Node):
    id = "motors.telemetry"
    name = "Motors Telemetry"
    kind = "sensors.motors"
    resources = ["serial"]
    topics_out = ["motors"]

    def __init__(
        self,
        bus: TelemetryBus,
        locks: ResourceLocks,
        config: DuckConfig,
    ) -> None:
        super().__init__(bus, locks)
        self.duck = config
        self._servo: Any = None
        self._config = {
            "serial_port": config.serial_port,
            "baudrate": config.baudrate,
            "poll_hz": config.poll_hz,
            "mock_hardware": config.mock_hardware,
        }

    async def on_start(self) -> None:
        mock = bool(self._config.get("mock_hardware", True))
        if not mock:
            try:
                from st3215 import ST3215  # type: ignore

                self._servo = ST3215(self._config["serial_port"])
                self.log(f"opened ST3215 on {self._config['serial_port']}")
            except Exception as exc:  # noqa: BLE001
                self.log(f"ST3215 unavailable ({exc}); falling back to mock")
                self._config["mock_hardware"] = True
                self._servo = None
        self._task = asyncio.create_task(self._poll_loop(), name="motors-poll")

    async def on_stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._servo = None
        await self.bus.update(motors={})

    async def on_kill(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()

    async def on_config(self, config: dict[str, Any]) -> None:
        self._config.update(config)

    async def _poll_loop(self) -> None:
        hz = float(self._config.get("poll_hz", 15))
        dt = 1.0 / max(hz, 1.0)
        t0 = time.time()
        while True:
            try:
                motors = await asyncio.to_thread(self._read_all, t0)
                await self.bus.update(motors=motors, nodes={self.id: NodeState.RUNNING.value})
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.error = str(exc)
                self.log(f"poll error: {exc}")
            await asyncio.sleep(dt)

    def _read_all(self, t0: float) -> dict[str, dict]:
        now = time.time() - t0
        out: dict[str, dict] = {}
        mock = bool(self._config.get("mock_hardware", True))
        for name, joint in self.duck.joints.items():
            if mock or self._servo is None:
                mid = (joint.min + joint.max) / 2
                amp = (joint.max - joint.min) / 4
                pos = mid + amp * math.sin(now * 0.7 + joint.id * 0.2)
                tel = MotorTelemetry(
                    id=joint.id,
                    name=name,
                    position=round(pos, 4),
                    position_raw=int(2048 + pos * (4096 / (2 * math.pi))),
                    temperature_c=round(35 + 5 * abs(math.sin(now + joint.id)), 1),
                    voltage_v=round(7.4 + 0.1 * math.sin(now * 0.3), 2),
                    current_ma=round(abs(200 + 150 * math.sin(now * 1.1 + joint.id)), 1),
                    load=round(100 * math.sin(now + joint.id), 1),
                    speed=round(200 * math.cos(now * 0.9 + joint.id), 1),
                    online=True,
                    status={
                        "Voltage": True,
                        "Sensor": True,
                        "Temperature": True,
                        "Current": True,
                        "Angle": True,
                        "Overload": True,
                    },
                )
            else:
                tel = self._read_real(name, joint.id)
            out[name] = tel.model_dump()
        return out

    def _read_real(self, name: str, sts_id: int) -> MotorTelemetry:
        s = self._servo
        pos_raw: Optional[int] = s.ReadPosition(sts_id)
        temp = s.ReadTemperature(sts_id)
        volt = s.ReadVoltage(sts_id)
        current = s.ReadCurrent(sts_id)
        load = s.ReadLoad(sts_id)
        speed_t = s.ReadSpeed(sts_id)
        status = s.ReadStatus(sts_id) or {}
        speed = 0.0
        if isinstance(speed_t, tuple) and speed_t:
            speed = float(speed_t[0] or 0)
        elif isinstance(speed_t, (int, float)):
            speed = float(speed_t)
        online = pos_raw is not None
        pos = _steps_to_rad(pos_raw) if pos_raw is not None else 0.0
        return MotorTelemetry(
            id=sts_id,
            name=name,
            position=round(pos, 4),
            position_raw=pos_raw,
            temperature_c=float(temp or 0),
            voltage_v=float(volt or 0),
            current_ma=float(current or 0),
            load=float(load or 0),
            speed=speed,
            online=online,
            status=status if isinstance(status, dict) else {},
        )
