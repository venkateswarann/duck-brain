"""Interactive SSH sessions bridged to a WebSocket.

Each browser terminal gets its own paramiko session running a real remote PTY,
so full-screen programs (htop, vim, less) and job control behave normally.
Credentials are supplied per connection and are never written to disk.
"""

from __future__ import annotations

import asyncio
import io
import select
import threading
from dataclasses import dataclass
from typing import Any

try:
    import paramiko

    HAVE_PARAMIKO = True
except ImportError:  # pragma: no cover - depends on deployment
    paramiko = None  # type: ignore[assignment]
    HAVE_PARAMIKO = False

# Terminal reads are chunked; this only bounds a single read, not the session.
READ_SIZE = 32768
CONNECT_TIMEOUT = 15.0


class SshError(Exception):
    """Raised with a message intended for display in the browser terminal."""


@dataclass
class SshTarget:
    host: str
    port: int = 22
    username: str = ""
    password: str | None = None
    private_key: str | None = None
    passphrase: str | None = None
    term: str = "xterm-256color"
    cols: int = 80
    rows: int = 24

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> SshTarget:
        # Hosts pasted from a browser often carry a trailing slash or a scheme.
        raw_host = str(payload.get("host") or "").strip()
        for prefix in ("ssh://", "http://", "https://"):
            if raw_host.lower().startswith(prefix):
                raw_host = raw_host[len(prefix) :]
        host = raw_host.strip("/").strip()
        if "@" in host:
            host = host.rsplit("@", 1)[1]
        if not host:
            raise SshError("No host given")

        # Allow host:port as a convenience, but an explicit port wins.
        port = payload.get("port")
        if ":" in host and not host.startswith("["):
            head, _, tail = host.rpartition(":")
            if tail.isdigit():
                host = head
                port = port or int(tail)

        username = str(payload.get("username") or payload.get("user") or "").strip()
        if not username:
            raise SshError("No username given")

        try:
            port_num = int(port or 22)
        except (TypeError, ValueError):
            raise SshError(f"Invalid port: {port!r}") from None
        if not 1 <= port_num <= 65535:
            raise SshError(f"Port out of range: {port_num}")

        def _clean(value: Any) -> str | None:
            text = str(value or "")
            return text or None

        return cls(
            host=host,
            port=port_num,
            username=username,
            password=_clean(payload.get("password")),
            private_key=_clean(payload.get("private_key")),
            passphrase=_clean(payload.get("passphrase")),
            cols=int(payload.get("cols") or 80),
            rows=int(payload.get("rows") or 24),
        )


class SshSession:
    """A connected SSH shell. All blocking paramiko work runs in a thread."""

    def __init__(self, target: SshTarget):
        self.target = target
        self._client: Any = None
        self._channel: Any = None
        self._queue: asyncio.Queue[bytes] | None = None
        self._reader: threading.Thread | None = None
        self._stop = threading.Event()

    @property
    def banner(self) -> str:
        t = self.target
        return f"{t.username}@{t.host}:{t.port}"

    async def connect(self) -> None:
        if not HAVE_PARAMIKO:
            raise SshError(
                "paramiko is not installed on the backend. Install it with:\n"
                "  cd backend && source .venv/bin/activate && pip install paramiko"
            )
        await asyncio.get_running_loop().run_in_executor(None, self._connect_blocking)

    def _connect_blocking(self) -> None:
        t = self.target
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        # Robots are commonly reflashed, so a changed host key is expected and a
        # hard failure here would just block the user from their own hardware.
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        kwargs: dict[str, Any] = {
            "hostname": t.host,
            "port": t.port,
            "username": t.username,
            "timeout": CONNECT_TIMEOUT,
            "banner_timeout": CONNECT_TIMEOUT,
            "auth_timeout": CONNECT_TIMEOUT,
            "allow_agent": True,
            "look_for_keys": t.private_key is None and t.password is None,
        }

        if t.private_key:
            kwargs["pkey"] = self._load_key(t.private_key, t.passphrase)
        elif t.password:
            kwargs["password"] = t.password
            # Some sshd setups only offer keyboard-interactive for passwords.
            kwargs["look_for_keys"] = False

        try:
            client.connect(**kwargs)
        except paramiko.AuthenticationException:
            client.close()
            raise SshError(
                f"Authentication failed for {t.username}@{t.host}. "
                "Check the username, password or key."
            ) from None
        except paramiko.SSHException as exc:
            client.close()
            raise SshError(f"SSH error: {exc}") from None
        except OSError as exc:
            client.close()
            raise SshError(f"Cannot reach {t.host}:{t.port} — {exc}") from None

        channel = client.invoke_shell(term=t.term, width=t.cols, height=t.rows)
        channel.settimeout(0.0)
        self._client = client
        self._channel = channel

    @staticmethod
    def _load_key(material: str, passphrase: str | None) -> Any:
        # Resolved by name because the available key types vary by paramiko
        # version (DSSKey was dropped in 5.0).
        candidates = [
            getattr(paramiko, name, None)
            for name in ("Ed25519Key", "ECDSAKey", "RSAKey", "DSSKey")
        ]
        key_classes = [cls for cls in candidates if cls is not None]

        errors = []
        for key_cls in key_classes:
            try:
                return key_cls.from_private_key(io.StringIO(material), password=passphrase)
            except paramiko.SSHException as exc:
                errors.append(f"{key_cls.__name__}: {exc}")
            except (ValueError, TypeError) as exc:
                errors.append(f"{key_cls.__name__}: {exc}")

        tried = ", ".join(cls.__name__.replace("Key", "") for cls in key_classes)
        raise SshError(
            f"Could not read the private key (tried {tried}). "
            "If it is encrypted, provide the passphrase.\n" + "\n".join(errors)
        )

    def start_reader(self) -> None:
        """Pump remote output into a queue from a dedicated thread.

        A thread per session rather than run_in_executor: a reader blocks for as
        long as the session lives, which would permanently occupy workers in the
        shared executor and stall other sessions.
        """
        loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()
        self._reader = threading.Thread(target=self._read_loop, args=(loop,), daemon=True)
        self._reader.start()

    def _read_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        channel = self._channel

        def emit(chunk: bytes) -> None:
            if self._queue is not None:
                loop.call_soon_threadsafe(self._queue.put_nowait, chunk)

        try:
            while channel is not None and not self._stop.is_set():
                if channel.closed:
                    break
                readable, _, _ = select.select([channel], [], [], 0.2)
                if not readable:
                    if not channel.active:
                        break
                    continue
                got_data = False
                if channel.recv_ready():
                    data = channel.recv(READ_SIZE)
                    if not data:
                        break
                    emit(data)
                    got_data = True
                if channel.recv_stderr_ready():
                    data = channel.recv_stderr(READ_SIZE)
                    if data:
                        emit(data)
                        got_data = True
                if not got_data and channel.exit_status_ready():
                    break
        except Exception:  # noqa: BLE001 - any failure ends the session
            pass
        finally:
            emit(b"")  # sentinel: shell finished

    async def read(self) -> bytes:
        """Return the next chunk of output, or b"" once the shell exits."""
        if self._queue is None:
            return b""
        return await self._queue.get()

    def write(self, data: str | bytes) -> None:
        channel = self._channel
        if channel is None or channel.closed:
            return
        payload = data.encode("utf-8") if isinstance(data, str) else data
        try:
            channel.sendall(payload)
        except OSError:
            pass

    def resize(self, cols: int, rows: int) -> None:
        channel = self._channel
        if channel is None or channel.closed:
            return
        try:
            channel.resize_pty(width=max(int(cols), 1), height=max(int(rows), 1))
        except Exception:  # noqa: BLE001 - resizing is best effort
            pass

    def close(self) -> None:
        self._stop.set()
        for closeable in (self._channel, self._client):
            try:
                if closeable is not None:
                    closeable.close()
            except Exception:  # noqa: BLE001
                pass
        self._channel = None
        self._client = None
