from __future__ import annotations

import asyncio
import os
import platform
import socket
import time
from typing import Any

import psutil

from ..runtime.base_node import Node
from ..runtime.bus import TelemetryBus
from ..runtime.locks import ResourceLocks
from ..schemas import NodeState


class SystemMetricsNode(Node):
    id = "system.metrics"
    name = "System Metrics"
    kind = "system"
    resources: list[str] = []
    topics_out = ["system"]

    def __init__(self, bus: TelemetryBus, locks: ResourceLocks) -> None:
        super().__init__(bus, locks)
        self._config = {"interval_s": 1.0}

    async def on_start(self) -> None:
        psutil.cpu_percent(interval=None)
        self._task = asyncio.create_task(self._loop(), name="system-metrics")

    async def on_stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        while True:
            data = await asyncio.to_thread(self._sample)
            await self.bus.update(system=data, nodes={self.id: NodeState.RUNNING.value})
            await asyncio.sleep(float(self._config.get("interval_s", 1.0)))

    def _sample(self) -> dict[str, Any]:
        vm = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        nets = []
        for name, addrs in psutil.net_if_addrs().items():
            for a in addrs:
                if getattr(a, "family", None) == socket.AF_INET:
                    nets.append({"iface": name, "ip": a.address})
        procs = []
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"]):
            try:
                info = p.info
                rss = 0.0
                mi = info.get("memory_info")
                if mi is not None:
                    rss = mi.rss / (1024 * 1024)
                procs.append(
                    {
                        "pid": info["pid"],
                        "name": info.get("name") or "?",
                        "cpu_percent": info.get("cpu_percent") or 0.0,
                        "memory_mib": round(rss, 2),
                    }
                )
            except (psutil.Error, KeyError):
                continue
        procs.sort(key=lambda x: x["cpu_percent"], reverse=True)
        return {
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "uptime_s": int(time.time() - psutil.boot_time()),
            "cpu_percent": psutil.cpu_percent(interval=None),
            "ram": {
                "total_mib": round(vm.total / (1024 * 1024), 1),
                "used_mib": round(vm.used / (1024 * 1024), 1),
                "percent": vm.percent,
            },
            "disk": {
                "total_gb": round(disk.total / (1024**3), 2),
                "used_gb": round(disk.used / (1024**3), 2),
                "percent": disk.percent,
            },
            "ips": nets,
            "processes": procs[:25],
            "pid": os.getpid(),
        }
