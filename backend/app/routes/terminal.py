"""WebSocket terminals: remote SSH shells and an optional local PTY.

Wire format (JSON, both directions):
    client -> {"type": "connect", ...target}   open the session (SSH only)
    client -> {"type": "input", "data": "ls"}  keystrokes
    client -> {"type": "resize", "cols", "rows"}
    server -> {"type": "status", "state": "...", "message": "..."}
    server -> {"type": "output", "data": "..."}
    server -> {"type": "exit", "message": "..."}

Output is decoded as UTF-8 with errors replaced, so partial multi-byte
sequences never break the stream.
"""

from __future__ import annotations

import asyncio
import codecs
import json
import os
from typing import Any

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

from ..services.ssh import HAVE_PARAMIKO, SshError, SshSession, SshTarget

router = APIRouter(tags=["terminal"])


async def _send(ws: WebSocket, payload: dict[str, Any]) -> None:
    try:
        await ws.send_text(json.dumps(payload))
    except (RuntimeError, WebSocketDisconnect):
        pass


async def _status(ws: WebSocket, state: str, message: str = "") -> None:
    await _send(ws, {"type": "status", "state": state, "message": message})


@router.get("/api/terminal/capabilities")
async def terminal_capabilities(request: Request):
    cfg = request.app.state.duck
    local_enabled = bool(cfg.allow_web_terminal) and os.environ.get("ALLOW_WEB_TERMINAL") == "1"
    return {
        "ssh": {
            "available": HAVE_PARAMIKO,
            "hint": "" if HAVE_PARAMIKO else "pip install paramiko in backend/.venv",
        },
        "local_pty": {
            "available": local_enabled,
            "allow_web_terminal": bool(cfg.allow_web_terminal),
            "env_flag": os.environ.get("ALLOW_WEB_TERMINAL") == "1",
            "hint": (
                ""
                if local_enabled
                else "Set allow_web_terminal=true in duck_config.json and ALLOW_WEB_TERMINAL=1 in the backend environment."
            ),
        },
    }


@router.websocket("/ws/ssh")
async def ssh_terminal(ws: WebSocket):
    await ws.accept()
    session: SshSession | None = None
    pump: asyncio.Task[None] | None = None

    try:
        # The first message carries the target and credentials. Credentials stay
        # in memory for the lifetime of this socket and are never persisted.
        try:
            first = json.loads(await ws.receive_text())
        except (json.JSONDecodeError, TypeError):
            await _status(ws, "error", "Expected a JSON connect message")
            return

        if first.get("type") != "connect":
            await _status(ws, "error", "First message must be {'type': 'connect'}")
            return

        try:
            target = SshTarget.from_payload(first)
        except SshError as exc:
            await _status(ws, "error", str(exc))
            return

        await _status(ws, "connecting", f"Connecting to {target.username}@{target.host}:{target.port}…")

        session = SshSession(target)
        try:
            await session.connect()
        except SshError as exc:
            await _status(ws, "error", str(exc))
            return

        session.start_reader()
        await _status(ws, "connected", session.banner)

        pump = asyncio.create_task(_pump_output(ws, session))

        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            kind = msg.get("type")
            if kind == "input":
                session.write(str(msg.get("data") or ""))
            elif kind == "resize":
                session.resize(int(msg.get("cols") or 80), int(msg.get("rows") or 24))
            elif kind == "disconnect":
                break

    except WebSocketDisconnect:
        pass
    finally:
        if pump is not None:
            pump.cancel()
        if session is not None:
            session.close()


async def _pump_output(ws: WebSocket, session: SshSession) -> None:
    """Forward remote output until the shell exits."""
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    try:
        while True:
            chunk = await session.read()
            if not chunk:
                await _send(ws, {"type": "exit", "message": "Session closed by remote host"})
                return
            await _send(ws, {"type": "output", "data": decoder.decode(chunk)})
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        await _send(ws, {"type": "exit", "message": f"Stream error: {exc}"})


@router.websocket("/ws/pty")
async def local_pty(ws: WebSocket):
    """A shell on the machine running the backend.

    Off unless both duck_config.allow_web_terminal and ALLOW_WEB_TERMINAL=1 are
    set: unlike the SSH terminal, this needs no credentials and hands out the
    backend user's shell to anyone who can reach the port.
    """
    await ws.accept()

    cfg = ws.app.state.duck
    if not cfg.allow_web_terminal or os.environ.get("ALLOW_WEB_TERMINAL") != "1":
        await _status(
            ws,
            "error",
            "Local terminal is disabled. Set allow_web_terminal=true in duck_config.json "
            "and start the backend with ALLOW_WEB_TERMINAL=1.",
        )
        await ws.close()
        return

    import fcntl
    import pty
    import signal
    import struct
    import termios

    shell = os.environ.get("SHELL") or "/bin/bash"
    pid, fd = pty.fork()
    if pid == 0:  # child
        os.environ["TERM"] = "xterm-256color"
        os.execvp(shell, [shell, "-i"])
        os._exit(1)

    loop = asyncio.get_running_loop()
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    def resize(cols: int, rows: int) -> None:
        try:
            fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        except OSError:
            pass

    async def pump() -> None:
        while True:
            try:
                data = await loop.run_in_executor(None, os.read, fd, 32768)
            except OSError:
                data = b""
            if not data:
                await _send(ws, {"type": "exit", "message": "Shell exited"})
                return
            await _send(ws, {"type": "output", "data": decoder.decode(data)})

    await _status(ws, "connected", f"{shell} on {os.uname().nodename}")
    task = asyncio.create_task(pump())

    try:
        while True:
            msg = json.loads(await ws.receive_text())
            kind = msg.get("type")
            if kind == "input":
                os.write(fd, str(msg.get("data") or "").encode("utf-8"))
            elif kind in ("resize", "connect"):
                # The opening `connect` message carries the terminal's initial size.
                resize(int(msg.get("cols") or 80), int(msg.get("rows") or 24))
            elif kind == "disconnect":
                break
    except (WebSocketDisconnect, json.JSONDecodeError, OSError):
        pass
    finally:
        task.cancel()
        try:
            os.kill(pid, signal.SIGHUP)
        except OSError:
            pass
        try:
            os.close(fd)
        except OSError:
            pass
