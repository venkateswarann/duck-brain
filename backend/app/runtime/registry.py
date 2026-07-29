from __future__ import annotations

from typing import Optional

from .base_node import Node
from .bus import TelemetryBus
from .locks import ResourceBusyError, ResourceLocks
from ..schemas import NodeInfo, NodeState


class NodeRegistry:
    def __init__(self, bus: TelemetryBus, locks: ResourceLocks) -> None:
        self.bus = bus
        self.locks = locks
        self._nodes: dict[str, Node] = {}

    def register(self, node: Node) -> None:
        self._nodes[node.id] = node

    def get(self, node_id: str) -> Node:
        if node_id not in self._nodes:
            raise KeyError(node_id)
        return self._nodes[node_id]

    def list(self) -> list[NodeInfo]:
        return [n.info() for n in self._nodes.values()]

    def get_optional(self, node_id: str) -> Optional[Node]:
        return self._nodes.get(node_id)

    async def start(self, node_id: str) -> NodeInfo:
        node = self.get(node_id)
        try:
            await node.start()
        except ResourceBusyError as exc:
            # Prefer script policy: if serial busy by motors.telemetry, pause it
            if exc.resource == "serial" and exc.holder == "motors.telemetry":
                motors = self.get_optional("motors.telemetry")
                if motors and motors.state == NodeState.RUNNING:
                    await motors.stop()
                    await node.start()
                else:
                    raise
            else:
                raise
        return node.info()

    async def stop(self, node_id: str) -> NodeInfo:
        node = self.get(node_id)
        await node.stop()
        # Auto-resume motors telemetry when serial freed
        if "serial" in node.resources:
            motors = self.get_optional("motors.telemetry")
            if motors and motors.state == NodeState.STOPPED:
                try:
                    await motors.start()
                except Exception:  # noqa: BLE001
                    pass
        return node.info()

    async def kill(self, node_id: str) -> NodeInfo:
        node = self.get(node_id)
        await node.kill()
        if "serial" in node.resources:
            motors = self.get_optional("motors.telemetry")
            if motors and motors.state == NodeState.STOPPED:
                try:
                    await motors.start()
                except Exception:  # noqa: BLE001
                    pass
        return node.info()

    async def restart(self, node_id: str) -> NodeInfo:
        await self.kill(node_id)
        return await self.start(node_id)

    async def start_enabled(self, enabled: dict[str, bool]) -> None:
        for node_id, on in enabled.items():
            node = self._nodes.get(node_id)
            if node and on:
                try:
                    await node.start()
                except Exception as exc:  # noqa: BLE001
                    node.log(f"auto-start failed: {exc}")
