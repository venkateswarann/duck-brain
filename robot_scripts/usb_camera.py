#!/usr/bin/env python3
"""USBCamera

Publishes frames to the DCS Camera page: pick "usb_camera" in the Source
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
        print(f"could not open camera {device}", file=sys.stderr, flush=True)
        return 1
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)

    stream = VideoStream("usb_camera", label="USBCamera", fps=FPS)
    print(f"streaming {device} at {WIDTH}x{HEIGHT} as 'usb_camera'", flush=True)

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
                print(f"published {frames} frames", flush=True)
            stream.wait_for_next_frame()
    finally:
        cap.release()
        stream.close()
    print(f"stopped after {frames} frames", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
