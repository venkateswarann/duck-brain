from __future__ import annotations

import asyncio
from typing import Any, Optional

import httpx

from ..runtime.base_node import Node
from ..runtime.bus import TelemetryBus
from ..runtime.locks import ResourceLocks
from ..schemas import DuckConfig


class EyesUnavailable(RuntimeError):
    pass


class EyesLinkNode(Node):
    """Talks to the eyes service on the head Pi Zero (devices/head_zero/eyes_server.py).

    companion.eyes_urls lists candidate addresses (USB link, LAN, Tailscale);
    the first that answers /health is used, and the list is probed again
    whenever the current one stops answering.
    """

    id = "eyes.link"
    name = "Eyes Link (head Pi Zero)"
    kind = "actuators.eyes"
    topics_out = ["companion"]

    def __init__(self, bus: TelemetryBus, locks: ResourceLocks, config: DuckConfig) -> None:
        super().__init__(bus, locks)
        self.urls = list(config.companion.eyes_urls)
        self.url: Optional[str] = None
        self.last_state: dict[str, Any] = {}
        self._client: Optional[httpx.AsyncClient] = None
        self._config = {"eyes_urls": self.urls}

    async def on_start(self) -> None:
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(2.0, connect=1.0))
        self._task = asyncio.create_task(self._poll_loop(), name="eyes-poll")

    async def on_stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._client:
            await self._client.aclose()
            self._client = None
        self.url = None
        await self.bus.update(companion={"eyes": {"online": False}})

    async def on_config(self, config: dict[str, Any]) -> None:
        if "eyes_urls" in config:
            self.urls = list(config["eyes_urls"])
            self.url = None

    @property
    def online(self) -> bool:
        return self.url is not None

    async def request(self, method: str, path: str, json: Any = None) -> Any:
        if self._client is None:
            raise EyesUnavailable("eyes.link node is not running")
        if self.url is None:
            await self._discover()
        if self.url is None:
            raise EyesUnavailable(f"eyes service not reachable at {self.urls}")
        try:
            resp = await self._client.request(method, f"{self.url}{path}", json=json)
        except httpx.HTTPError as exc:
            self.url = None
            raise EyesUnavailable(f"eyes service error: {exc}") from exc
        if resp.status_code >= 400:
            detail = resp.json().get("detail") if "json" in resp.headers.get("content-type", "") else resp.text
            raise ValueError(detail)
        if resp.headers.get("content-type", "").startswith("image/"):
            return resp.content
        return resp.json()

    async def _discover(self) -> None:
        assert self._client is not None
        for url in self.urls:
            try:
                r = await self._client.get(f"{url.rstrip('/')}/health")
                if r.status_code == 200:
                    self.url = url.rstrip("/")
                    self.log(f"eyes service found at {self.url} (mock={r.json().get('mock')})")
                    return
            except httpx.HTTPError:
                continue

    async def _poll_loop(self) -> None:
        was_online = None
        while True:
            try:
                self.last_state = await self.request("GET", "/state")
            except (EyesUnavailable, ValueError):
                self.last_state = {}
            if was_online is not None and was_online != self.online:
                self.log("eyes ONLINE" if self.online else "eyes OFFLINE; retrying")
            was_online = self.online
            await self.bus.update(
                companion={"eyes": {"online": self.online, "url": self.url, "state": self.last_state}}
            )
            await asyncio.sleep(1.0 if self.online else 3.0)
