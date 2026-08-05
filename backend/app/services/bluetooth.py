from __future__ import annotations

import asyncio
import re
import shutil
from typing import Any


class BluetoothError(RuntimeError):
    pass


def bluetoothctl_available() -> bool:
    return shutil.which("bluetoothctl") is not None


async def _run_bt(*args: str, timeout: float = 8.0) -> str:
    if not bluetoothctl_available():
        raise BluetoothError(
            "bluetoothctl not found. Install bluez (e.g. sudo apt install bluez)."
        )
    proc = await asyncio.create_subprocess_exec(
        "bluetoothctl",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise BluetoothError(f"bluetoothctl timed out: {' '.join(args)}") from exc
    out = (out_b or b"").decode(errors="replace")
    err = (err_b or b"").decode(errors="replace")
    text = (out + "\n" + err).strip()
    if proc.returncode not in (0, None) and "Failed" in text:
        raise BluetoothError(text or f"bluetoothctl exited {proc.returncode}")
    return text


async def _run_script(commands: list[str], timeout: float = 45.0) -> str:
    """Feed multiple bluetoothctl commands via stdin (for scan/pair sessions)."""
    if not bluetoothctl_available():
        raise BluetoothError(
            "bluetoothctl not found. Install bluez (e.g. sudo apt install bluez)."
        )
    script = "\n".join(commands) + "\nquit\n"
    proc = await asyncio.create_subprocess_exec(
        "bluetoothctl",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out_b, err_b = await asyncio.wait_for(
            proc.communicate(script.encode()), timeout=timeout
        )
    except asyncio.TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise BluetoothError("bluetoothctl session timed out") from exc
    return ((out_b or b"") + (err_b or b"")).decode(errors="replace")


_MAC_RE = re.compile(r"([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})")


def _parse_devices(text: str) -> list[dict[str, Any]]:
    devices: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if "Device " not in line:
            continue
        m = _MAC_RE.search(line)
        if not m:
            continue
        mac = m.group(1).upper()
        name = line[m.end() :].strip() or mac
        devices.append({"address": mac, "name": name})
    seen: dict[str, dict[str, Any]] = {}
    for d in devices:
        seen[d["address"]] = d
    return list(seen.values())


async def adapter_status() -> dict[str, Any]:
    available = bluetoothctl_available()
    if not available:
        return {
            "available": False,
            "powered": False,
            "discoverable": False,
            "pairable": False,
            "scanning": False,
            "error": "bluetoothctl not installed",
        }
    try:
        show = await _run_bt("show", timeout=4.0)
    except BluetoothError as exc:
        return {
            "available": True,
            "powered": False,
            "discoverable": False,
            "pairable": False,
            "scanning": False,
            "error": str(exc),
            "hint": "Is bluetoothd running? Try: sudo systemctl start bluetooth",
        }
    def flag(key: str) -> bool:
        m = re.search(rf"{key}:\s*(yes|no)", show, re.I)
        return bool(m and m.group(1).lower() == "yes")

    return {
        "available": True,
        "powered": flag("Powered"),
        "discoverable": flag("Discoverable"),
        "pairable": flag("Pairable"),
        "scanning": flag("Discovering"),
        "raw": show,
        "error": None,
    }


async def list_devices() -> list[dict[str, Any]]:
    text = await _run_bt("devices", timeout=6.0)
    devices = _parse_devices(text)
    paired: set[str] = set()
    for cmd in (("devices", "Paired"), ("paired-devices",)):
        try:
            paired_text = await _run_bt(*cmd, timeout=4.0)
            paired |= {d["address"] for d in _parse_devices(paired_text)}
            break
        except BluetoothError:
            continue
    connected: set[str] = set()
    for cmd in (("devices", "Connected"),):
        try:
            conn_text = await _run_bt(*cmd, timeout=4.0)
            connected = {d["address"] for d in _parse_devices(conn_text)}
        except BluetoothError:
            pass
    for d in devices:
        d["paired"] = d["address"] in paired
        d["connected"] = d["address"] in connected
    return devices


async def scan(duration_s: float = 8.0) -> list[dict[str, Any]]:
    duration_s = max(3.0, min(float(duration_s), 30.0))
    await _run_bt("power", "on")
    # Interactive scan: power on, scan on, wait, scan off, devices
    await _run_script(
        [
            "power on",
            "agent on",
            "default-agent",
            "scan on",
        ],
        timeout=10.0,
    )
    await asyncio.sleep(duration_s)
    await _run_script(["scan off"], timeout=10.0)
    return await list_devices()


async def pair_device(address: str) -> dict[str, Any]:
    address = address.upper().strip()
    if not _MAC_RE.fullmatch(address):
        raise BluetoothError("Invalid MAC address")
    await _run_bt("power", "on")
    log = await _run_script(
        [
            "power on",
            "agent on",
            "default-agent",
            f"pair {address}",
            f"trust {address}",
            f"connect {address}",
        ],
        timeout=60.0,
    )
    return {"ok": True, "address": address, "log": log}


async def connect_device(address: str) -> dict[str, Any]:
    address = address.upper().strip()
    log = await _run_bt("connect", address, timeout=30.0)
    return {"ok": True, "address": address, "log": log}


async def disconnect_device(address: str) -> dict[str, Any]:
    address = address.upper().strip()
    log = await _run_bt("disconnect", address, timeout=20.0)
    return {"ok": True, "address": address, "log": log}


async def remove_device(address: str) -> dict[str, Any]:
    address = address.upper().strip()
    log = await _run_bt("remove", address, timeout=20.0)
    return {"ok": True, "address": address, "log": log}


async def _rfkill_unblock() -> str:
    """Attempt to soft-unblock the Bluetooth adapter via rfkill.

    rfkill is the kernel RF-kill subsystem.  BlueZ returns
    org.bluez.Error.Failed when the adapter's PowerState is 'off-blocked',
    which means rfkill has the adapter blocked.  We must unblock it before
    bluetoothctl can power the adapter on.
    """
    if not shutil.which("rfkill"):
        return "rfkill not found (skipped)"
    proc = await asyncio.create_subprocess_exec(
        "rfkill", "unblock", "bluetooth",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=5.0)
    return ((out_b or b"") + (err_b or b"")).decode(errors="replace").strip()


async def set_powered(on: bool) -> dict[str, Any]:
    rfkill_log = ""
    if on:
        # If the adapter is rfkill-blocked (PowerState: off-blocked),
        # bluetoothctl will return org.bluez.Error.Failed.  Unblock first.
        try:
            status = await adapter_status()
            if status.get("raw", "").find("off-blocked") != -1 or not status.get("powered"):
                rfkill_log = await _rfkill_unblock()
                # Give BlueZ a moment to register the unblock
                await asyncio.sleep(0.5)
        except Exception:  # noqa: BLE001
            pass
    try:
        log = await _run_bt("power", "on" if on else "off")
    except BluetoothError as exc:
        # If still failing after rfkill unblock, provide a clearer message
        msg = str(exc)
        if "Failed" in msg and on:
            raise BluetoothError(
                f"Could not power on Bluetooth adapter. "
                f"rfkill output: '{rfkill_log or 'n/a'}'. "
                f"BlueZ error: {msg}. "
                f"If there is a hard block (physical switch or firmware), "
                f"rfkill cannot clear it — check 'rfkill list' on the device."
            ) from exc
        raise
    return {"ok": True, "powered": on, "log": (rfkill_log + "\n" + log).strip()}
