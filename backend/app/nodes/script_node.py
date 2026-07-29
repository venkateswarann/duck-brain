from __future__ import annotations

import asyncio
import os
import signal
import sys
from pathlib import Path
from typing import Any, Optional

import psutil

from ..config_loader import SCRIPTS_DIR
from ..runtime.base_node import Node
from ..runtime.bus import TelemetryBus
from ..runtime.locks import ResourceLocks


class ScriptNode(Node):
    """Runnable Python file under robot_scripts/."""

    kind = "script"

    def __init__(
        self,
        bus: TelemetryBus,
        locks: ResourceLocks,
        script_path: Path,
        display_name: Optional[str] = None,
        resources: Optional[list[str]] = None,
        depends_on: Optional[list[str]] = None,
        description: str = "",
    ) -> None:
        super().__init__(bus, locks)
        self.script_path = script_path
        self.id = f"script.{script_path.stem}"
        self.name = display_name or script_path.name
        self.resources = list(resources or [])
        self.depends_on = list(depends_on or [])
        self.topics_out = [f"script.{script_path.stem}"]
        self._config = {
            "path": str(script_path),
            "description": description,
            "args": [],
        }
        self._child: Optional[asyncio.subprocess.Process] = None
        self._reader_tasks: list[asyncio.Task] = []

    async def on_start(self) -> None:
        if not self.script_path.exists():
            raise FileNotFoundError(self.script_path)
        args = [sys.executable, str(self.script_path), *self._config.get("args", [])]
        self._child = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(SCRIPTS_DIR),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "DCS_NODE_ID": self.id},
        )
        try:
            self._proc = psutil.Process(self._child.pid)
            self._proc.cpu_percent(interval=None)
        except psutil.Error:
            self._proc = None
        self.log(f"spawned pid={self._child.pid}")
        self._reader_tasks = [
            asyncio.create_task(self._pump(self._child.stdout, "stdout")),
            asyncio.create_task(self._pump(self._child.stderr, "stderr")),
            asyncio.create_task(self._wait_child()),
        ]

    async def on_stop(self) -> None:
        await self._terminate_child(force=False)

    async def on_kill(self) -> None:
        await self._terminate_child(force=True)

    async def _terminate_child(self, force: bool) -> None:
        for t in self._reader_tasks:
            t.cancel()
        self._reader_tasks.clear()
        child = self._child
        self._child = None
        self._proc = None
        if child is None or child.returncode is not None:
            return
        try:
            if force:
                child.send_signal(signal.SIGKILL)
            else:
                child.send_signal(signal.SIGTERM)
                try:
                    await asyncio.wait_for(child.wait(), timeout=3)
                except asyncio.TimeoutError:
                    child.send_signal(signal.SIGKILL)
                    await child.wait()
        except ProcessLookupError:
            pass
        self.log("process exited")

    async def _pump(self, stream: asyncio.StreamReader | None, label: str) -> None:
        if stream is None:
            return
        while True:
            line = await stream.readline()
            if not line:
                break
            text = line.decode(errors="replace").rstrip()
            self.log(f"[{label}] {text}")

    async def _wait_child(self) -> None:
        if self._child is None:
            return
        code = await self._child.wait()
        self.log(f"exit code={code}")
        if self.state.value == "running":
            # Process died unexpectedly
            from ..schemas import NodeState

            self.state = NodeState.ERROR if code else NodeState.STOPPED
            self.locks.release(self.id)
            await self.bus.publish_event(
                {"type": "stopped", "node_id": self.id, "exit_code": code}
            )
            await self.bus.update(nodes={self.id: self.state.value})


def discover_script_nodes(
    bus: TelemetryBus,
    locks: ResourceLocks,
    manifest: dict[str, Any],
) -> list[ScriptNode]:
    scripts_meta = manifest.get("scripts", {})
    nodes: list[ScriptNode] = []
    if not SCRIPTS_DIR.exists():
        return nodes
    for path in sorted(SCRIPTS_DIR.glob("*.py")):
        meta = scripts_meta.get(path.name, {})
        nodes.append(
            ScriptNode(
                bus=bus,
                locks=locks,
                script_path=path,
                display_name=meta.get("display_name"),
                resources=meta.get("resources"),
                depends_on=meta.get("depends_on"),
                description=meta.get("description", ""),
            )
        )
    return nodes
