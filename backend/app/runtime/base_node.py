from __future__ import annotations

import abc
import asyncio
import socket
import time
from typing import Any, Optional

import psutil

from ..schemas import NodeInfo, NodeState
from .bus import TelemetryBus
from .locks import ResourceLocks


class Node(abc.ABC):
    id: str
    name: str
    kind: str
    resources: list[str] = []
    topics_out: list[str] = []
    depends_on: list[str] = []

    def __init__(self, bus: TelemetryBus, locks: ResourceLocks) -> None:
        self.bus = bus
        self.locks = locks
        self.state = NodeState.CREATED
        self.error: Optional[str] = None
        self._started_at: Optional[float] = None
        self._proc: Optional[psutil.Process] = None
        self._task: Optional[asyncio.Task] = None
        self._config: dict[str, Any] = {}
        self._host = socket.gethostname()

    def log(self, line: str) -> None:
        self.bus.append_log(self.id, line)

    def info(self) -> NodeInfo:
        cpu = 0.0
        mem = 0.0
        open_files = 0
        pid = None
        if self._proc is not None:
            try:
                if self._proc.is_running():
                    pid = self._proc.pid
                    cpu = float(self._proc.cpu_percent(interval=None))
                    mem = float(self._proc.memory_info().rss) / (1024 * 1024)
                    try:
                        open_files = len(self._proc.open_files())
                    except (psutil.AccessDenied, psutil.Error):
                        open_files = 0
            except psutil.Error:
                pass
        return NodeInfo(
            id=self.id,
            name=self.name,
            kind=self.kind,
            state=self.state,
            pid=pid,
            cpu_percent=round(cpu, 2),
            memory_mib=round(mem, 2),
            open_files=open_files,
            host=self._host,
            error=self.error,
            resources=list(self.resources),
            topics_out=list(self.topics_out),
            depends_on=list(self.depends_on),
            config=dict(self._config),
        )

    async def start(self) -> None:
        if self.state == NodeState.RUNNING:
            return
        self.state = NodeState.STARTING
        self.error = None
        await self.bus.publish_event({"type": "starting", "node_id": self.id})
        try:
            if self.resources:
                self.locks.acquire(self.resources, self.id)
            await self.on_start()
            self.state = NodeState.RUNNING
            self._started_at = time.time()
            self.log(f"started")
            await self.bus.publish_event({"type": "started", "node_id": self.id})
            await self.bus.update(nodes={self.id: self.state.value})
        except Exception as exc:  # noqa: BLE001
            self.state = NodeState.ERROR
            self.error = str(exc)
            self.locks.release(self.id)
            self.log(f"ERROR start: {exc}")
            await self.bus.publish_event(
                {"type": "error", "node_id": self.id, "error": str(exc)}
            )
            await self.bus.update(nodes={self.id: self.state.value})
            raise

    async def stop(self) -> None:
        if self.state in (NodeState.STOPPED, NodeState.CREATED):
            return
        self.state = NodeState.STOPPING
        await self.bus.publish_event({"type": "stopping", "node_id": self.id})
        try:
            await self.on_stop()
        finally:
            self.locks.release(self.id)
            self.state = NodeState.STOPPED
            self._started_at = None
            self.log("stopped")
            await self.bus.publish_event({"type": "stopped", "node_id": self.id})
            await self.bus.update(nodes={self.id: self.state.value})

    async def kill(self) -> None:
        self.log("kill requested")
        await self.on_kill()
        await self.stop()
        await self.bus.publish_event({"type": "killed", "node_id": self.id})

    async def restart(self) -> None:
        await self.kill()
        await self.start()

    def get_config(self) -> dict[str, Any]:
        return dict(self._config)

    async def set_config(self, config: dict[str, Any]) -> None:
        self._config.update(config)
        await self.on_config(config)

    @abc.abstractmethod
    async def on_start(self) -> None: ...

    @abc.abstractmethod
    async def on_stop(self) -> None: ...

    async def on_kill(self) -> None:
        """Forceful teardown hook; default same as stop path extras."""

    async def on_config(self, config: dict[str, Any]) -> None:
        return None
