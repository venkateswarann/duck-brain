"""Connection to the robot (DCS on the Pi 4): MCP for decisions, REST for reflexes."""

from __future__ import annotations

import asyncio
import base64
import json
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Awaitable, Callable, Optional
from urllib.parse import urlsplit

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from .trace import Trace


class RobotOffline(RuntimeError):
    pass


class Robot:
    """Finds DCS among candidate URLs and talks to it.

    Gemma's chosen actions go through MCP tool calls (the same tools any agent
    or the Agent Skill would use). The fast reflex loop (face tracking,
    listening/thinking eyes) uses plain REST to keep latency down; both paths
    hit the same clamped endpoints on the robot.
    """

    def __init__(self, urls: list[str], trace: Trace) -> None:
        self.urls = [u.rstrip("/") for u in urls]
        self.trace = trace
        self.base: Optional[str] = None
        # Called after (re)connecting, e.g. to switch breathing back on after the Pi 4 rebooted.
        self.on_connect: Optional[Callable[[], Awaitable[None]]] = None
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(4.0, connect=1.5))

    @property
    def link(self) -> str:
        if not self.base:
            return "offline"
        host = urlsplit(self.base).hostname or ""
        if host.startswith("100.") or ("." not in host and host != "localhost"):
            return "tailscale"
        return "local" if host in ("127.0.0.1", "localhost") else "lan"

    async def discover(self) -> Optional[str]:
        for url in self.urls:
            try:
                r = await self.http.get(f"{url}/api/health", timeout=1.5)
                if r.status_code == 200:
                    reconnected = self.base != url
                    if reconnected:
                        self.trace.emit("robot", status="ok", detail=f"connected to DCS at {url}")
                    self.base = url
                    if reconnected and self.on_connect is not None:
                        asyncio.create_task(self.on_connect())
                    self.trace.set_state(robot_url=url, link=self.link)
                    return url
            except httpx.HTTPError:
                continue
        if self.base is not None:
            self.trace.emit("robot", status="error", detail="DCS unreachable on all URLs")
        self.base = None
        self.trace.set_state(robot_url=None, link="offline")
        return None

    async def watch_loop(self) -> None:
        """Re-find DCS within a few seconds when it drops (Pi 4 reboot, Wi-Fi blip)."""
        while True:
            if self.base is None:
                await self.discover()
            else:
                try:
                    r = await self.http.get(f"{self.base}/api/health", timeout=2.0)
                    if r.status_code != 200:
                        raise httpx.HTTPError("unhealthy")
                except httpx.HTTPError:
                    self.base = None
                    await self.discover()
            await asyncio.sleep(2.0)

    async def _base(self) -> str:
        if self.base is None and await self.discover() is None:
            raise RobotOffline(f"no DCS answering at {self.urls}")
        assert self.base is not None
        return self.base

    # ------------------------------------------------------------------ REST

    async def get(self, path: str) -> Any:
        base = await self._base()
        try:
            r = await self.http.get(f"{base}{path}")
        except httpx.HTTPError as exc:
            self.base = None
            raise RobotOffline(str(exc)) from exc
        r.raise_for_status()
        return r.json() if "json" in r.headers.get("content-type", "") else r.content

    async def post(self, path: str, body: Any = None) -> Any:
        base = await self._base()
        try:
            r = await self.http.post(f"{base}{path}", json=body)
        except httpx.HTTPError as exc:
            self.base = None
            raise RobotOffline(str(exc)) from exc
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail")
            except ValueError:
                detail = r.text
            return {"ok": False, "detail": detail, "http_status": r.status_code}
        return r.json()

    async def snapshot_b64(self, stream: str) -> Optional[str]:
        try:
            data = await self.get(f"/api/video/snapshot/{stream}")
        except (RobotOffline, httpx.HTTPStatusError):
            return None
        return base64.b64encode(data).decode() if isinstance(data, bytes) else None

    async def snapshot_jpeg(self, stream: str) -> Optional[bytes]:
        try:
            data = await self.get(f"/api/video/snapshot/{stream}")
        except (RobotOffline, httpx.HTTPStatusError):
            return None
        return data if isinstance(data, bytes) else None

    async def heartbeat_loop(self, detail: str) -> None:
        while True:
            try:
                await self.post("/api/companion/heartbeat", {"name": "duck-brain", "detail": detail})
            except RobotOffline:
                await self.discover()
            await asyncio.sleep(3.0)

    # ------------------------------------------------------------------ MCP

    @asynccontextmanager
    async def mcp(self) -> AsyncIterator[ClientSession]:
        base = await self._base()
        async with streamablehttp_client(f"{base}/mcp") as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session

    async def call_tools(self, calls: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
        """Run several MCP tool calls in order over one session; returns parsed results."""
        results: list[dict[str, Any]] = []
        if not calls:
            return results
        async with self.mcp() as session:
            for tool, args in calls:
                started = time.monotonic()
                res = await session.call_tool(tool, args)
                text = res.content[0].text if res.content else ""
                try:
                    parsed = json.loads(text)
                except (json.JSONDecodeError, TypeError):
                    parsed = {"text": text}
                if isinstance(parsed, dict):
                    parsed.setdefault("ok", not res.isError)
                results.append({"tool": tool, "args": args, "result": parsed,
                                "ms": round((time.monotonic() - started) * 1000)})
        return results

    async def close(self) -> None:
        await self.http.aclose()
