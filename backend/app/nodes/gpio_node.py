"""GpioPinsNode — lifecycle-managed node for GPIO pin control.

Initialises the GpioService, sets up all enabled devices from the pinout
config, and runs probe loops.  Appears as ``gpio.pins`` in the System /
Nodes page.
"""
from __future__ import annotations

import asyncio
from typing import Any

from ..runtime.base_node import Node
from ..runtime.bus import TelemetryBus
from ..runtime.locks import ResourceLocks
from ..services.gpio import Direction, GpioService, Pull


class GpioPinsNode(Node):
    id = "gpio.pins"
    name = "GPIO Pins"
    kind = "gpio"
    resources: list[str] = []      # GPIO doesn't contend with serial/camera
    topics_out: list[str] = ["gpio"]

    def __init__(
        self,
        bus: TelemetryBus,
        locks: ResourceLocks,
        *,
        mock: bool = True,
        pinout: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(bus, locks)
        self._mock = mock
        self._pinout = pinout or {}
        self.gpio: GpioService | None = None

    async def on_start(self) -> None:
        self.gpio = GpioService(mock=self._mock, bus=self.bus, node_id=self.id)
        self.gpio.init_hardware()
        self.log(f"GPIO service started (mock={self._mock})")

        # Auto-setup devices from pinout config
        devices = self._pinout.get("devices") or []
        for dev in devices:
            if not dev.get("enabled", True):
                continue
            if dev.get("reserved", False):
                continue

            pins = dev.get("pins", {})
            signal_pin = pins.get("signal")
            if signal_pin is None:
                continue
            try:
                signal_pin = int(signal_pin)
            except (ValueError, TypeError):
                self.log(f"skipping {dev.get('id', '?')}: pin not a number")
                continue

            mode = dev.get("mode", "OUT").upper()
            direction = Direction.IN if mode == "IN" else Direction.OUT
            pull_str = dev.get("pull", "NONE").upper()
            pull = Pull.UP if pull_str == "UP" else Pull.DOWN if pull_str == "DOWN" else Pull.NONE

            self.gpio.setup_pin(
                signal_pin,
                direction,
                pull=pull,
                device_id=dev.get("id"),
                label=dev.get("label"),
            )

            # Set default value for outputs
            if direction == Direction.OUT:
                default = int(dev.get("default_value", 0))
                self.gpio.write_pin(signal_pin, default)

            # Auto-start probe for input pins
            if direction == Direction.IN and dev.get("probe", False):
                rate = float(dev.get("probe_rate_hz", 50))
                await self.gpio.start_probe(signal_pin, rate)

        self.log(f"configured {len([d for d in devices if d.get('enabled', True) and not d.get('reserved', False)])} device(s)")

    async def on_stop(self) -> None:
        if self.gpio:
            # Stop all probes
            for bcm in list(self.gpio._probes):
                await self.gpio.stop_probe(bcm)
            self.gpio.cleanup_all()
            self.gpio = None
        self.log("GPIO service stopped")

    async def on_kill(self) -> None:
        if self.gpio:
            self.gpio.cleanup_all()
            self.gpio = None

    async def reload_pinout(self, pinout: dict[str, Any]) -> None:
        """Update pinout config and apply any newly-enabled devices to the live GPIO service.

        Called automatically by PUT /api/pinout so new devices take effect
        immediately without restarting the node.
        """
        self._pinout = pinout
        if self.gpio is None:
            return  # node not running yet — on_start will pick up the new config

        devices = pinout.get("devices") or []
        for dev in devices:
            if not dev.get("enabled", True) or dev.get("reserved", False):
                continue

            pins = dev.get("pins", {})
            signal_pin = pins.get("signal")
            if signal_pin is None:
                continue
            try:
                signal_pin = int(signal_pin)
            except (ValueError, TypeError):
                self.log(f"skipping {dev.get('id', '?')}: pin not a number")
                continue

            # Skip pins already registered — don't reinitialise a live pin
            if signal_pin in self.gpio._pins:
                continue

            mode = dev.get("mode", "OUT").upper()
            direction = Direction.IN if mode == "IN" else Direction.OUT
            pull_str = dev.get("pull", "NONE").upper()
            pull = Pull.UP if pull_str == "UP" else Pull.DOWN if pull_str == "DOWN" else Pull.NONE

            self.gpio.setup_pin(
                signal_pin, direction, pull=pull,
                device_id=dev.get("id"), label=dev.get("label"),
            )

            if direction == Direction.OUT:
                self.gpio.write_pin(signal_pin, int(dev.get("default_value", 0)))

            if direction == Direction.IN and dev.get("probe", False):
                rate = float(dev.get("probe_rate_hz", 50))
                await self.gpio.start_probe(signal_pin, rate)

