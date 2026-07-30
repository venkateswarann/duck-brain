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
from ..services import script_fs
from ..services.script_templates import stream_id_for


class ScriptNode(Node):
    """Runnable Python file under robot_scripts/ (any depth)."""

    kind = "script"

    def __init__(
        self,
        bus: TelemetryBus,
        locks: ResourceLocks,
        script_path: Path,
        rel_path: Optional[str] = None,
        display_name: Optional[str] = None,
        resources: Optional[list[str]] = None,
        depends_on: Optional[list[str]] = None,
        description: str = "",
        args: Optional[list[str]] = None,
    ) -> None:
        super().__init__(bus, locks)
        self.script_path = script_path
        self.rel_path = rel_path or script_fs.relative(script_path)
        self.id = script_fs.node_id_for(self.rel_path)
        self.name = display_name or self.rel_path
        self.resources = list(resources or [])
        self.depends_on = list(depends_on or [])
        self.topics_out = [self.id]
        self._config = {
            "path": self.rel_path,
            "description": description,
            "args": [str(a) for a in (args or [])],
        }
        self._child: Optional[asyncio.subprocess.Process] = None
        self._pumps: list[asyncio.Task] = []
        self._waiter: Optional[asyncio.Task] = None

    def _script_args(self) -> list[str]:
        raw = self._config.get("args") or []
        if isinstance(raw, str):
            return raw.split()
        return [str(a) for a in raw]

    def _child_env(self) -> dict[str, str]:
        python_path = script_fs.script_python_path(self.script_path)
        existing = os.environ.get("PYTHONPATH")
        if existing:
            python_path.append(existing)
        port = os.environ.get("DCS_BACKEND_PORT", "8000")
        return {
            **os.environ,
            "PYTHONPATH": os.pathsep.join(python_path),
            "PYTHONUNBUFFERED": "1",
            "DCS_NODE_ID": self.id,
            "DCS_SCRIPT": self.rel_path,
            "DCS_STREAM_ID": stream_id_for(Path(self.rel_path).stem),
            "DCS_API_URL": os.environ.get("DCS_API_URL", f"http://127.0.0.1:{port}"),
        }

    async def on_start(self) -> None:
        if not self.script_path.exists():
            raise FileNotFoundError(self.script_path)
        args = [sys.executable]
        if sys.version_info >= (3, 11):
            # Keep the script's folder out of sys.path[0] so the PYTHONPATH
            # order below decides which package wins.
            args.append("-P")
        args += [str(self.script_path), *self._script_args()]
        self._child = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(self.script_path.parent),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._child_env(),
        )
        try:
            self._proc = psutil.Process(self._child.pid)
            self._proc.cpu_percent(interval=None)
        except psutil.Error:
            self._proc = None
        self.log(f"spawned pid={self._child.pid} ({self.rel_path})")
        self._pumps = [
            asyncio.create_task(self._pump(self._child.stdout, "stdout")),
            asyncio.create_task(self._pump(self._child.stderr, "stderr")),
        ]
        self._waiter = asyncio.create_task(self._wait_child(self._child))

    async def on_stop(self) -> None:
        await self._terminate_child(force=False)

    async def on_kill(self) -> None:
        await self._terminate_child(force=True)

    async def _terminate_child(self, force: bool) -> None:
        child = self._child
        pumps, waiter = self._pumps, self._waiter
        self._child = None
        self._pumps = []
        self._waiter = None
        self._proc = None
        if child is None or child.returncode is not None:
            for task in (*pumps, waiter):
                if task is not None:
                    task.cancel()
            return
        try:
            child.send_signal(signal.SIGKILL if force else signal.SIGTERM)
        except ProcessLookupError:
            pass
        # Drain stdout/stderr before awaiting the process: the pumps see EOF
        # when the child exits, and reaping it first loses the last lines the
        # script printed from its SIGTERM handler (uvloop closes the pipes).
        if pumps:
            await asyncio.wait(pumps, timeout=0.5 if force else 2.0)
        try:
            await asyncio.wait_for(child.wait(), timeout=1.5)
        except asyncio.TimeoutError:
            self.log("did not exit on SIGTERM; sending SIGKILL")
            try:
                child.send_signal(signal.SIGKILL)
                await asyncio.wait_for(child.wait(), timeout=2)
            except (ProcessLookupError, asyncio.TimeoutError):
                pass
        except ProcessLookupError:
            pass
        for task in (*pumps, waiter):
            if task is not None:
                task.cancel()
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

    async def _wait_child(self, child: asyncio.subprocess.Process) -> None:
        code = await child.wait()
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


def make_script_node(
    bus: TelemetryBus,
    locks: ResourceLocks,
    rel_path: str,
    path: Optional[Path] = None,
) -> ScriptNode:
    """Build a node for one script, pulling metadata from manifest.json."""
    meta = script_fs.manifest_meta(rel_path)
    return ScriptNode(
        bus=bus,
        locks=locks,
        script_path=path or (SCRIPTS_DIR / rel_path),
        rel_path=rel_path,
        display_name=meta.get("display_name"),
        resources=meta.get("resources"),
        depends_on=meta.get("depends_on"),
        description=meta.get("description", ""),
        args=meta.get("args"),
    )


def discover_script_nodes(
    bus: TelemetryBus,
    locks: ResourceLocks,
    manifest: dict[str, Any],
) -> list[ScriptNode]:
    """Register nodes for manifest-listed scripts only.

    robot_scripts/ also holds library packages (mini_bdx_runtime/), so the
    manifest is what marks a file as a runnable node. Anything else gets a node
    created on demand when it is run from the Scripts page.
    """
    scripts_meta = manifest.get("scripts", {})
    if not isinstance(scripts_meta, dict) or not SCRIPTS_DIR.exists():
        return []
    nodes: list[ScriptNode] = []
    seen: set[str] = set()
    for key in sorted(scripts_meta):
        rel = key.replace("\\", "/").strip("/")
        path = SCRIPTS_DIR / rel
        if not path.is_file() or path.suffix != ".py":
            continue
        rel = script_fs.relative(path)
        if rel in seen:
            continue
        seen.add(rel)
        nodes.append(make_script_node(bus, locks, rel, path))
    return nodes
