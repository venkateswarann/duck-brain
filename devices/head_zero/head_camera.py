#!/usr/bin/env python3
"""Streams the head's CSI camera into DCS as the "head_cam" video stream.

Uses Picamera2 with the hardware MJPEG encoder, so the Zero's CPU stays free
for the eye animation: no numpy, no OpenCV in the frame path. Each JPEG is
POSTed to DCS (dcs_sdk.VideoStream.publish_jpeg); if a POST is still in flight
when the next frame arrives, the older frame is dropped so latency stays low.

    python3 head_camera.py --dcs http://10.55.0.1:8000 http://pi4.local:8000
    python3 head_camera.py --mock --dcs http://127.0.0.1:8000     # no camera
"""

from __future__ import annotations

import argparse
import io
import os
import signal
import sys
import threading
import time
from typing import Optional

HERE = os.path.dirname(os.path.abspath(__file__))
# dcs_sdk.py is copied next to this file on deploy; in the repo it lives in robot_scripts/.
sys.path.extend([HERE, os.path.join(HERE, "..", "..", "robot_scripts")])
from dcs_sdk import VideoStream, find_backend  # noqa: E402

STREAM_ID = "head_cam"


class LatestFrameSender:
    """Holds only the newest JPEG and sends it from a worker thread."""

    def __init__(self, candidates: list[str], label: str, width: int, height: int) -> None:
        self.candidates = candidates
        self.label = label
        self.width = width
        self.height = height
        self._frame: Optional[bytes] = None
        self._cond = threading.Condition()
        self._stop = threading.Event()
        self._stream: Optional[VideoStream] = None
        self.sent = 0
        self.dropped = 0
        self._thread = threading.Thread(target=self._run, name="frame-sender", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
        self._thread.join(timeout=3)
        if self._stream:
            self._stream.close()

    def offer(self, jpeg: bytes) -> None:
        with self._cond:
            if self._frame is not None:
                self.dropped += 1
            self._frame = jpeg
            self._cond.notify()

    def _connect(self) -> None:
        while not self._stop.is_set():
            base = find_backend(self.candidates)
            if base:
                print(f"publishing '{STREAM_ID}' to {base}", flush=True)
                self._stream = VideoStream(STREAM_ID, label=self.label, base_url=base)
                return
            print(f"no DCS backend answering at {self.candidates}; retrying", flush=True)
            self._stop.wait(3.0)

    def _run(self) -> None:
        failures = 0
        while not self._stop.is_set():
            if self._stream is None:
                self._connect()
                continue
            with self._cond:
                while self._frame is None and not self._stop.is_set():
                    self._cond.wait(timeout=1.0)
                jpeg, self._frame = self._frame, None
            if jpeg is None:
                continue
            if self._stream.publish_jpeg(jpeg, self.width, self.height):
                self.sent += 1
                failures = 0
            else:
                failures += 1
                if failures >= 10:  # backend moved (e.g. LAN -> Tailscale): look again
                    self._stream.close()
                    self._stream = None
                    failures = 0


class _EncoderSink(io.BufferedIOBase):
    """Picamera2 FileOutput target: each write() is one complete JPEG."""

    def __init__(self, sender: LatestFrameSender) -> None:
        self.sender = sender

    def writable(self) -> bool:
        return True

    def write(self, buf) -> int:  # type: ignore[override]
        self.sender.offer(bytes(buf))
        return len(buf)


def run_picamera(args: argparse.Namespace, sender: LatestFrameSender, stop: threading.Event) -> None:
    from libcamera import Transform  # noqa: PLC0415
    from picamera2 import Picamera2  # noqa: PLC0415
    from picamera2.outputs import FileOutput  # noqa: PLC0415

    if not Picamera2.global_camera_info():
        raise RuntimeError("libcamera sees no camera; check the ribbon and `rpicam-hello --list-cameras`")

    cam = Picamera2()
    frame_us = int(1_000_000 / args.fps)
    config = cam.create_video_configuration(
        main={"size": (args.width, args.height), "format": "YUV420"},
        transform=Transform(hflip=args.hflip, vflip=args.vflip),
        controls={"FrameDurationLimits": (frame_us, frame_us)},
        buffer_count=4,
    )
    cam.configure(config)
    try:
        from picamera2.encoders import MJPEGEncoder  # noqa: PLC0415

        encoder = MJPEGEncoder(bitrate=args.bitrate)
        kind = "hardware MJPEG"
    except Exception:  # noqa: BLE001  (no V4L2 JPEG encoder, e.g. Pi 5)
        from picamera2.encoders import JpegEncoder  # noqa: PLC0415

        encoder = JpegEncoder(q=args.quality)
        kind = "software JPEG"
    cam.start_recording(encoder, FileOutput(_EncoderSink(sender)))
    print(f"camera running: {args.width}x{args.height}@{args.fps:g}fps, {kind}", flush=True)
    try:
        while not stop.wait(10.0):
            print(f"sent {sender.sent} frames, dropped {sender.dropped}", flush=True)
    finally:
        cam.stop_recording()
        cam.close()


def run_mock(args: argparse.Namespace, sender: LatestFrameSender, stop: threading.Event) -> None:
    """Synthetic frames so the whole pipeline can be tested without a Pi."""
    from PIL import Image, ImageDraw  # noqa: PLC0415

    print("mock camera running", flush=True)
    period = 1.0 / args.fps
    n = 0
    while not stop.is_set():
        img = Image.new("RGB", (args.width, args.height), (30, 30, 36))
        draw = ImageDraw.Draw(img)
        x = int((n * 6) % args.width)
        draw.ellipse((x - 40, args.height // 2 - 40, x + 40, args.height // 2 + 40), fill=(220, 40, 40))
        draw.text((12, 12), f"head_cam mock {time.strftime('%H:%M:%S')}  #{n}", fill=(200, 200, 200))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=args.quality)
        sender.offer(buf.getvalue())
        n += 1
        stop.wait(period)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dcs", nargs="+", default=[os.environ.get("DCS_API_URL", "http://10.55.0.1:8000")],
                        help="candidate DCS base URLs, first that answers wins")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=float, default=15.0)
    parser.add_argument("--quality", type=int, default=75)
    parser.add_argument("--bitrate", type=int, default=6_000_000, help="MJPEG encoder bitrate")
    parser.add_argument("--hflip", action="store_true")
    parser.add_argument("--vflip", action="store_true")
    parser.add_argument("--mock", action="store_true", help="synthetic frames, no camera")
    args = parser.parse_args()

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    sender = LatestFrameSender(args.dcs, "Head camera", args.width, args.height)
    sender.start()
    try:
        (run_mock if args.mock else run_picamera)(args, sender, stop)
    finally:
        sender.stop()
    print(f"stopped: sent {sender.sent}, dropped {sender.dropped}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
