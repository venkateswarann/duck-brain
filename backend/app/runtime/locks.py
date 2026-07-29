from __future__ import annotations

from dataclasses import dataclass


class ResourceBusyError(RuntimeError):
    def __init__(self, resource: str, holder: str) -> None:
        self.resource = resource
        self.holder = holder
        super().__init__(f"Resource '{resource}' held by '{holder}'")


@dataclass
class LockRecord:
    resource: str
    holder: str


class ResourceLocks:
    """Exclusive locks for serial, camera, etc."""

    def __init__(self) -> None:
        self._held: dict[str, str] = {}

    def acquire(self, resources: list[str], holder: str) -> None:
        for res in resources:
            current = self._held.get(res)
            if current and current != holder:
                raise ResourceBusyError(res, current)
        for res in resources:
            self._held[res] = holder

    def release(self, holder: str) -> None:
        for res, h in list(self._held.items()):
            if h == holder:
                del self._held[res]

    def holder(self, resource: str) -> str | None:
        return self._held.get(resource)

    def snapshot(self) -> dict[str, str]:
        return dict(self._held)
