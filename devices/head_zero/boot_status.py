#!/usr/bin/env python3
"""Boot status screens on the duck's eyes, shown until the robot is ready.

Left eye  = this Pi Zero: hostname, USB link to the Pi 4, Wi-Fi/Tailscale IP, camera.
Right eye = the Pi 4 (polled over the USB link): DCS backend, servos, mic,
            speaker, brain (laptop) heartbeat.

When the required checks pass it starts duck-eyes.service; the units declare
Conflicts= on each other, so systemd stops this process (and its SPI handles)
before the eyes take the displays. If duck-eyes fails, its OnFailure= brings
this screen back with the error instead of a frozen eye.

    sudo python3 boot_status.py              # on the Zero, normally via systemd
    python3 boot_status.py --mock --once     # render one frame to boot_status.png
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from eye_renderer import HEIGHT, WIDTH, load_calibration, open_displays  # noqa: E402

GREEN = (60, 210, 110)
RED = (235, 70, 70)
AMBER = (240, 180, 50)
GREY = (120, 120, 130)
TEXT = (230, 235, 240)
BG = (0, 0, 0)
SAFE = 170  # text stays inside the central 170 px square, clear of the round edge
FAIL_COUNT_FILE = "/run/duck-boot-status.failures"


@dataclass
class Check:
    label: str
    ok: Optional[bool]  # None = still waiting
    detail: str = ""
    required: bool = True


# ------------------------------------------------------------------ checks


def _run(cmd: list[str], timeout: float = 5.0) -> str:
    if not shutil.which(cmd[0]):
        return ""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _iface_ipv4(name_prefixes: tuple[str, ...]) -> dict[str, str]:
    out = _run(["ip", "-j", "-4", "addr"])
    found: dict[str, str] = {}
    try:
        for iface in json.loads(out or "[]"):
            name = iface.get("ifname", "")
            if name.startswith(name_prefixes):
                for addr in iface.get("addr_info", []):
                    found[name] = addr.get("local", "")
    except json.JSONDecodeError:
        pass
    return found


_camera_cache: dict[str, object] = {}


def _camera_present() -> tuple[Optional[bool], str]:
    # rpicam-hello takes a few seconds and holds the camera, so only ask until it answers yes.
    if _camera_cache.get("ok"):
        return True, str(_camera_cache["detail"])
    if _run(["systemctl", "is-active", "duck-headcam.service"]).strip() == "active":
        return True, "streaming"  # the camera is busy streaming, so don't probe it
    out = _run(["rpicam-hello", "--list-cameras"], timeout=10) or _run(
        ["libcamera-hello", "--list-cameras"], timeout=10
    )
    for line in out.splitlines():
        line = line.strip()
        if line[:1].isdigit() and ":" in line:
            sensor = line.split(":", 1)[1].strip().split(" ")[0]
            _camera_cache.update(ok=True, detail=sensor)
            return True, sensor
    return False, "not detected"


def zero_checks(usb_ip: str, mock: bool) -> list[Check]:
    if mock:
        return [
            Check("host", True, socket.gethostname()),
            Check("usb link", True, usb_ip),
            Check("network", True, "100.101.1.2", required=False),
            Check("camera", True, "imx219"),
        ]
    ips = _iface_ipv4(("usb", "wlan", "tailscale"))
    usb_ok = any(ip == usb_ip for ip in ips.values())
    net = ips.get("tailscale0") or ips.get("wlan0") or ""
    cam_ok, cam_detail = _camera_present()
    return [
        Check("host", True, socket.gethostname()),
        Check("usb link", usb_ok, usb_ip if usb_ok else "down"),
        Check("network", bool(net), net or "offline", required=False),
        Check("camera", cam_ok, cam_detail),
    ]


def pi4_checks(dcs_url: str, mock: bool) -> list[Check]:
    if mock:
        return [
            Check("dcs", True, "up"),
            Check("servos", True, "4/4"),
            Check("mic", True, "usb"),
            Check("speaker", True, "ok"),
            Check("brain", None, "waiting", required=False),
        ]
    try:
        with urllib.request.urlopen(f"{dcs_url}/api/companion/status", timeout=2) as resp:
            status = json.load(resp)
    except Exception:  # noqa: BLE001
        return [Check("dcs", None, "waiting")] + [
            Check(name, None, "-", required=False) for name in ("servos", "mic", "speaker", "brain")
        ]
    servos = status.get("servos", {})
    audio = status.get("audio", {})
    brain = status.get("brain", {})
    return [
        Check("dcs", True, "up"),
        Check("servos", servos.get("ok"), f"{servos.get('found', 0)}/{servos.get('expected', 0)}", required=False),
        Check("mic", audio.get("mic"), "ok" if audio.get("mic") else "missing", required=False),
        Check("speaker", audio.get("speaker"), "ok" if audio.get("speaker") else "missing", required=False),
        Check("brain", brain.get("online"), brain.get("detail", "waiting"), required=False),
    ]


# ------------------------------------------------------------------ drawing


def _font(size: int):
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ):
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


TITLE_FONT = _font(18)
ROW_FONT = _font(14)
SMALL_FONT = _font(11)


def _mark(draw: ImageDraw.ImageDraw, x: int, y: int, ok: Optional[bool]) -> None:
    if ok is None:
        draw.ellipse((x, y + 3, x + 9, y + 12), outline=AMBER, width=2)
    elif ok:
        draw.line((x, y + 8, x + 4, y + 12, x + 11, y + 2), fill=GREEN, width=3)
    else:
        draw.line((x, y + 2, x + 10, y + 12), fill=RED, width=3)
        draw.line((x + 10, y + 2, x, y + 12), fill=RED, width=3)


def draw_panel(title: str, checks: list[Check], spinner: float, footer: str = "") -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)
    cx = cy = WIDTH // 2

    done = sum(1 for c in checks if c.ok)
    frac = done / max(1, len(checks))
    ring = (6, 6, WIDTH - 6, HEIGHT - 6)
    draw.arc(ring, 0, 360, fill=(35, 35, 42), width=6)
    colour = GREEN if all(c.ok or not c.required for c in checks) else AMBER
    draw.arc(ring, -90, -90 + 360 * frac, fill=colour, width=6)
    if frac < 1:  # spinning dot shows the screen is alive
        a = spinner * 2 * math.pi
        r = WIDTH // 2 - 9
        x, y = cx + r * math.cos(a), cy + r * math.sin(a)
        draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=TEXT)

    left = cx - SAFE // 2
    top = cy - SAFE // 2
    draw.text((cx, top + 6), title, font=TITLE_FONT, fill=TEXT, anchor="mt")
    y = top + 34
    for c in checks:
        _mark(draw, left + 2, y, c.ok)
        draw.text((left + 18, y), c.label, font=ROW_FONT, fill=TEXT if c.required else GREY)
        draw.text((left + SAFE, y + 1), c.detail[:12], font=SMALL_FONT, fill=GREY, anchor="ra")
        y += 21
    if footer:
        draw.text((cx, top + SAFE - 4), footer[:26], font=SMALL_FONT, fill=RED, anchor="mb")
    return img


# ------------------------------------------------------------------ main


def _eyes_failure_reason() -> str:
    if _run(["systemctl", "is-failed", "duck-eyes.service"]).strip() != "failed":
        return ""
    last = _run(["journalctl", "-u", "duck-eyes.service", "-n", "1", "--no-pager", "-o", "cat"]).strip()
    return f"eyes crashed: {last}" if last else "eyes crashed"


def _bump_failures() -> int:
    try:
        n = int(open(FAIL_COUNT_FILE).read().strip() or 0) + 1
    except (OSError, ValueError):
        n = 1
    try:
        with open(FAIL_COUNT_FILE, "w") as f:
            f.write(str(n))
    except OSError:
        pass
    return n


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dcs", default="http://10.55.0.1:8000", help="DCS on the Pi 4 over the USB link")
    parser.add_argument("--usb-ip", default="10.55.0.2", help="this Zero's address on the USB link")
    parser.add_argument("--max-wait", type=float, default=180.0,
                        help="start the eyes anyway after this many seconds")
    parser.add_argument("--no-handover", action="store_true", help="just show status, never start duck-eyes")
    parser.add_argument("--mock", action="store_true", help="fake checks, no displays")
    parser.add_argument("--once", action="store_true", help="render one frame to boot_status.png and exit")
    args = parser.parse_args()

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    display = open_displays(args.mock, load_calibration())
    started = time.monotonic()
    footer = "" if args.mock else _eyes_failure_reason()
    hold_until = started + (20.0 if footer else 0.0)
    if footer and _bump_failures() > 3:
        args.no_handover = True  # eyes keep crashing: stay on the status screen
        footer = "eyes failed 3x: see journal"
    ready_since: Optional[float] = None

    zero: list[Check] = []
    pi4: list[Check] = []
    next_poll = 0.0
    frame = 0
    try:
        while not stop.is_set():
            now = time.monotonic()
            if now >= next_poll:
                zero = zero_checks(args.usb_ip, args.mock)
                pi4 = pi4_checks(args.dcs, args.mock)
                next_poll = now + 2.0
            spinner = (frame % 24) / 24
            left = draw_panel("duck head", zero, spinner, footer)
            right = draw_panel("duck body", pi4, spinner)
            display.show(left, right)
            frame += 1

            if args.once:
                canvas = Image.new("RGB", (WIDTH * 2 + 20, HEIGHT), BG)
                canvas.paste(right, (0, 0))
                canvas.paste(left, (WIDTH + 20, 0))
                canvas.save(os.path.join(HERE, "boot_status.png"))
                return 0

            required_ok = all(c.ok for c in zero + pi4 if c.required)
            ready_since = (ready_since or now) if required_ok else None
            timed_out = now - started >= args.max_wait
            if not args.no_handover and now >= hold_until and (
                (ready_since and now - ready_since >= 3.0) or timed_out
            ):
                # Conflicts= makes systemd stop us (SIGTERM) before duck-eyes starts.
                subprocess.run(["systemctl", "start", "--no-block", "duck-eyes.service"], check=False)
                stop.wait(10.0)
                break
            stop.wait(0.15)
    finally:
        display.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
