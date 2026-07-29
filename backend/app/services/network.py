from __future__ import annotations

import asyncio
import shutil
import socket
from typing import Any

import psutil


async def _run(cmd: list[str], timeout: float = 10.0) -> tuple[int, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out_b, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode or 0, (out_b or b"").decode(errors="replace")
    except FileNotFoundError:
        return 127, f"{cmd[0]} not found"
    except asyncio.TimeoutError:
        return 124, "timeout"


def _iface_summary() -> list[dict[str, Any]]:
    stats = psutil.net_if_stats()
    addrs = psutil.net_if_addrs()
    io = psutil.net_io_counters(pernic=True)
    rows: list[dict[str, Any]] = []
    for name, addr_list in sorted(addrs.items()):
        ipv4: list[str] = []
        ipv6: list[str] = []
        mac = None
        for a in addr_list:
            if a.family == socket.AF_INET:
                ipv4.append(a.address)
            elif a.family == socket.AF_INET6:
                ipv6.append(a.address.split("%")[0])
            elif getattr(a, "family", None) == psutil.AF_LINK:
                mac = a.address
        st = stats.get(name)
        counters = io.get(name)
        rows.append(
            {
                "name": name,
                "isup": bool(st.isup) if st else False,
                "speed_mbps": getattr(st, "speed", 0) if st else 0,
                "mtu": getattr(st, "mtu", None) if st else None,
                "ipv4": ipv4,
                "ipv6": ipv6,
                "mac": mac,
                "bytes_sent": getattr(counters, "bytes_sent", 0) if counters else 0,
                "bytes_recv": getattr(counters, "bytes_recv", 0) if counters else 0,
            }
        )
    return rows


async def network_snapshot() -> dict[str, Any]:
    ifaces = await asyncio.to_thread(_iface_summary)
    hostname = socket.gethostname()
    fqdn = socket.getfqdn()

    routes = ""
    code, routes = await _run(["ip", "route", "show"])
    if code != 0:
        code, routes = await _run(["route", "-n"])

    dns: list[str] = []
    try:
        text = open("/etc/resolv.conf", encoding="utf-8", errors="replace").read()
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("nameserver"):
                parts = line.split()
                if len(parts) >= 2:
                    dns.append(parts[1])
    except OSError:
        pass

    nmcli = shutil.which("nmcli") is not None
    wifi: dict[str, Any] = {"available": False}
    connections: list[dict[str, str]] = []
    if nmcli:
        wifi["available"] = True
        c, out = await _run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"])
        wifi["devices_raw"] = out if c == 0 else out
        devices = []
        for line in out.splitlines():
            parts = line.split(":")
            if len(parts) >= 4:
                devices.append(
                    {
                        "device": parts[0],
                        "type": parts[1],
                        "state": parts[2],
                        "connection": parts[3],
                    }
                )
        wifi["devices"] = devices

        c2, out2 = await _run(
            ["nmcli", "-t", "-f", "NAME,UUID,TYPE,DEVICE", "connection", "show"]
        )
        if c2 == 0:
            for line in out2.splitlines():
                parts = line.split(":")
                if len(parts) >= 4:
                    connections.append(
                        {
                            "name": parts[0],
                            "uuid": parts[1],
                            "type": parts[2],
                            "device": parts[3],
                        }
                    )
        # Wi-Fi scan (may need privileges)
        c3, out3 = await _run(
            ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY,IN-USE", "device", "wifi", "list"],
            timeout=15.0,
        )
        wifi["scan_ok"] = c3 == 0
        wifi["scan_error"] = None if c3 == 0 else out3.strip()
        networks = []
        if c3 == 0:
            for line in out3.splitlines():
                parts = line.split(":")
                if len(parts) >= 4:
                    networks.append(
                        {
                            "ssid": parts[0],
                            "signal": parts[1],
                            "security": parts[2],
                            "in_use": parts[3] == "*",
                        }
                    )
        wifi["networks"] = networks

    return {
        "hostname": hostname,
        "fqdn": fqdn,
        "interfaces": ifaces,
        "routes": routes.strip(),
        "dns": dns,
        "wifi": wifi,
        "connections": connections,
        "tools": {
            "nmcli": nmcli,
            "ip": shutil.which("ip") is not None,
        },
    }
