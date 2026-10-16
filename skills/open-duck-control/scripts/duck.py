#!/usr/bin/env python3
"""Minimal CLI for the Open Duck companion API (standard library only).

    python3 duck.py --robot http://duckpi4.local:8000 status
    python3 duck.py look 30 -10          # yaw pitch (degrees)
    python3 duck.py nod 2 | shake 2 | tilt 15 | center | stop
    python3 duck.py expression happy
    python3 duck.py gaze -0.5 0.2        # eyes only, -1..1
    python3 duck.py ears 0.5 0.5          # left right, -1..1
    python3 duck.py ear-gesture wiggle 2  # wiggle|perk|droop|flick_left|flick_right|alert
    python3 duck.py lamp on | lamp off | lamp 0.4
    python3 duck.py say "Hello there!"
    python3 duck.py estop

Prints the robot's JSON reply; clamped or rejected commands include "reasons".
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def call(base: str, method: str, path: str, body: object = None) -> object:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(f"{base.rstrip('/')}{path}", data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        return {"ok": False, "http_status": exc.code, "detail": exc.read().decode(errors="replace")}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--robot", default=os.environ.get("DUCK_URL", "http://127.0.0.1:8000"))
    p.add_argument("command")
    p.add_argument("args", nargs="*")
    a = p.parse_args()
    c, x = a.command, a.args
    routes = {
        "status": ("GET", "/api/companion/status", None),
        "look": ("POST", "/api/head/look_at", lambda: {"yaw": float(x[0]), "pitch": float(x[1])}),
        "nod": ("POST", "/api/head/nod", lambda: {"times": int(x[0]) if x else 1}),
        "shake": ("POST", "/api/head/shake", lambda: {"times": int(x[0]) if x else 1}),
        "tilt": ("POST", "/api/head/tilt", lambda: {"angle": float(x[0]) if x else 15}),
        "center": ("POST", "/api/head/center", None),
        "stop": ("POST", "/api/head/stop", None),
        "expression": ("POST", "/api/eyes/expression", lambda: {"name": x[0]}),
        "expressions": ("GET", "/api/eyes/expressions", None),
        "gaze": ("POST", "/api/eyes/look", lambda: {"x": float(x[0]), "y": float(x[1])}),
        "blink": ("POST", "/api/eyes/blink", None),
        "ears": ("POST", "/api/ears/set", lambda: {"left": float(x[0]), "right": float(x[1])}),
        "ear-gesture": ("POST", "/api/ears/gesture", lambda: {"name": x[0], "times": int(x[1]) if len(x) > 1 else 1}),
        "lamp": ("POST", "/api/lamp/set",
                 lambda: {"on": x[0] == "on"} if x[0] in ("on", "off") else {"brightness": float(x[0])}),
        "say": ("POST", "/api/speech/say", lambda: {"text": " ".join(x)}),
        "estop": ("POST", "/api/estop", None),
    }
    if c not in routes:
        p.error(f"unknown command {c!r}; one of: {', '.join(routes)}")
    method, path, body = routes[c]
    try:
        payload = body() if body else None
    except (IndexError, ValueError):
        p.error(f"bad arguments for {c}: {x}")
    print(json.dumps(call(a.robot, method, path, payload), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
