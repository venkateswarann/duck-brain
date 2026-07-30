"""Starter templates offered by the "New script" dialog on the Scripts page."""

from __future__ import annotations

import re
from typing import Any

BLANK = '''#!/usr/bin/env python3
"""{description}"""


def main() -> int:
    print("hello from {stem}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

LOOP = '''#!/usr/bin/env python3
"""{description}"""

import signal
import time

running = True


def _stop(*_args):
    # DCS sends SIGTERM when you press Stop; exit the loop so cleanup runs.
    global running
    running = False


def main() -> int:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    tick = 0
    while running:
        tick += 1
        print(f"tick {{tick}}", flush=True)
        time.sleep(1.0)

    print("stopped cleanly", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

USB_CAMERA = '''#!/usr/bin/env python3
"""{description}

Publishes frames to the DCS Camera page: pick "{stream_id}" in the Source
dropdown while this script is running.
"""

import os
import signal
import sys

import cv2

from dcs_sdk import VideoStream

DEVICE = os.environ.get("CAMERA_DEVICE", "0")
WIDTH = int(os.environ.get("CAMERA_WIDTH", "640"))
HEIGHT = int(os.environ.get("CAMERA_HEIGHT", "480"))
FPS = int(os.environ.get("CAMERA_FPS", "15"))

running = True


def _stop(*_args):
    global running
    running = False


def main() -> int:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    device = int(DEVICE) if DEVICE.isdigit() else DEVICE
    cap = cv2.VideoCapture(device)
    if not cap.isOpened():
        print(f"could not open camera {{device}}", file=sys.stderr, flush=True)
        return 1
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)

    stream = VideoStream("{stream_id}", label="{label}", fps=FPS)
    print(f"streaming {{device}} at {{WIDTH}}x{{HEIGHT}} as '{stream_id}'", flush=True)

    frames = 0
    try:
        while running:
            ok, frame = cap.read()
            if not ok:
                print("frame grab failed", file=sys.stderr, flush=True)
                continue
            stream.publish_frame(frame)
            frames += 1
            if frames % (FPS * 10) == 0:
                print(f"published {{frames}} frames", flush=True)
            stream.wait_for_next_frame()
    finally:
        cap.release()
        stream.close()
    print(f"stopped after {{frames}} frames", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

MOTORS = '''#!/usr/bin/env python3
"""{description}

Holds the "serial" resource lock: DCS pauses motors.telemetry while this runs
and resumes it on stop.
"""

import signal
import time

from mini_bdx_runtime.duck_config import DuckConfig
from mini_bdx_runtime.rustypot_position_hwi import HWI

running = True


def _stop(*_args):
    global running
    running = False


def main() -> int:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    hwi = HWI(DuckConfig())
    hwi.turn_on()
    try:
        while running:
            positions = hwi.get_present_positions()
            print({{name: round(float(p), 3) for name, p in zip(hwi.joints, positions)}}, flush=True)
            time.sleep(0.5)
    finally:
        hwi.turn_off()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

IMU = '''#!/usr/bin/env python3
"""{description}"""

import signal
import time

from mini_bdx_runtime.raw_imu import Imu

running = True


def _stop(*_args):
    global running
    running = False


def main() -> int:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    imu = Imu(sampling_freq=50, user_pitch_bias=0)
    while running:
        data = imu.get_data()
        if data:
            print(data, flush=True)
        time.sleep(0.1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

TEMPLATES: dict[str, dict[str, Any]] = {
    "blank": {
        "label": "Blank script",
        "hint": "Minimal main() skeleton.",
        "body": BLANK,
        "resources": [],
    },
    "loop": {
        "label": "Long-running loop",
        "hint": "Runs until Stop, handles SIGTERM cleanly.",
        "body": LOOP,
        "resources": [],
    },
    "usb_camera": {
        "label": "USB camera to Camera page",
        "hint": "Grabs OpenCV frames and publishes them as a video source.",
        "body": USB_CAMERA,
        "resources": ["camera0"],
    },
    "motors": {
        "label": "Motors / serial bus",
        "hint": "Reads joint positions through mini_bdx_runtime HWI.",
        "body": MOTORS,
        "resources": ["serial"],
    },
    "imu": {
        "label": "IMU reader",
        "hint": "Polls the BNO055 via mini_bdx_runtime.raw_imu.",
        "body": IMU,
        "resources": [],
    },
}


def list_templates() -> list[dict[str, Any]]:
    return [
        {
            "id": key,
            "label": value["label"],
            "hint": value["hint"],
            "resources": value["resources"],
        }
        for key, value in TEMPLATES.items()
    ]


def template_resources(template: str) -> list[str]:
    spec = TEMPLATES.get(template or "blank")
    return list(spec["resources"]) if spec else []


def stream_id_for(stem: str) -> str:
    slug = re.sub(r"[^a-z0-9_]+", "_", stem.lower()).strip("_")
    return slug or "script_stream"


def render(template: str, filename: str, description: str, display_name: str = "") -> str:
    spec = TEMPLATES.get(template or "blank")
    if spec is None:
        raise KeyError(template)
    stem = filename[:-3] if filename.endswith(".py") else filename
    label = display_name or stem.replace("_", " ").title()
    return spec["body"].format(
        description=description or label,
        stem=stem,
        label=label,
        stream_id=stream_id_for(stem),
    )
