#!/usr/bin/env python3
"""Streams a USB (or Raspberry Pi) camera to the DCS Camera page.

Run it from the Scripts page, then pick the stream in the Camera page Source
dropdown. Frames go to the backend through dcs_sdk, so this also works when you
launch it by hand:

    python3 camera.py --device 0 --width 640 --height 480 --fps 15
"""

from __future__ import annotations

import argparse
import signal
import sys
import time

from dcs_sdk import VideoStream, default_stream_id

running = True


def _stop(*_args) -> None:
    global running
    running = False


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--device",
        default="0",
        help="V4L2 index or path, e.g. 0 or /dev/video0 (default: 0)",
    )
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=float, default=15.0)
    parser.add_argument("--quality", type=int, default=70, help="JPEG quality 10-95")
    parser.add_argument(
        "--stream",
        default=default_stream_id(),
        help="Stream id shown in the Camera page Source dropdown",
    )
    parser.add_argument("--label", default="", help="Human readable stream name")
    parser.add_argument(
        "--backend",
        choices=("auto", "opencv", "picamera"),
        default="auto",
        help="Capture backend (default: auto, Picamera2 if libcamera sees a CSI camera, else OpenCV)",
    )
    return parser.parse_args(argv)


def open_opencv(args: argparse.Namespace):
    import cv2  # noqa: PLC0415

    device: object = int(args.device) if str(args.device).isdigit() else args.device
    capture = None
    if hasattr(cv2, "CAP_V4L2"):
        capture = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if capture is None or not capture.isOpened():
        if capture is not None:
            capture.release()
        capture = cv2.VideoCapture(device)
    if not capture.isOpened():
        capture.release()
        return None
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    capture.set(cv2.CAP_PROP_FPS, args.fps)
    return capture


def csi_camera_present() -> bool:
    try:
        from picamera2 import Picamera2  # noqa: PLC0415

        return bool(Picamera2.global_camera_info())
    except Exception:  # noqa: BLE001
        return False


def open_picamera(args: argparse.Namespace):
    from picamera2 import Picamera2  # noqa: PLC0415

    camera = Picamera2()
    camera.configure(
        camera.create_preview_configuration(
            main={"format": "RGB888", "size": (args.width, args.height)}
        )
    )
    camera.start()
    return camera


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    import cv2  # noqa: PLC0415

    capture = None
    picamera = None
    # On a Pi with a CSI camera, /dev/video0 is the unicam/codec node: OpenCV
    # "opens" it but never gets a frame, so Picamera2 has to be tried first.
    if args.backend == "picamera" or (args.backend == "auto" and csi_camera_present()):
        try:
            picamera = open_picamera(args)
        except Exception as exc:  # noqa: BLE001
            print(f"Picamera2 unavailable: {exc}", file=sys.stderr, flush=True)
    if picamera is None and args.backend in ("auto", "opencv"):
        capture = open_opencv(args)
        if capture is None:
            print(f"OpenCV could not open camera '{args.device}'", file=sys.stderr, flush=True)
    if capture is None and picamera is None:
        print("No camera could be opened — check the device and permissions", file=sys.stderr, flush=True)
        return 1

    stream = VideoStream(
        args.stream,
        label=args.label or f"Camera {args.device}",
        fps=args.fps,
        quality=args.quality,
    )
    backend = "opencv" if capture is not None else "picamera2"
    print(
        f"streaming '{args.stream}' via {backend} at {args.width}x{args.height}@{args.fps:g}fps",
        flush=True,
    )

    frames = 0
    failed_reads = 0
    started = time.time()
    try:
        while running:
            if capture is not None:
                ok, frame = capture.read()
                if not ok or frame is None:
                    failed_reads += 1
                    print("frame grab failed", file=sys.stderr, flush=True)
                    if failed_reads >= 25:
                        print("no frames from OpenCV after 25 tries; try --backend picamera",
                              file=sys.stderr, flush=True)
                        return 1
                    time.sleep(0.2)
                    continue
                failed_reads = 0
                if frame.shape[1] != args.width or frame.shape[0] != args.height:
                    frame = cv2.resize(frame, (args.width, args.height))
            else:
                # "RGB888" from libcamera is already BGR in memory: no conversion.
                frame = picamera.capture_array()

            if stream.publish_frame(frame):
                frames += 1
            if frames and frames % (max(1, int(args.fps)) * 10) == 0:
                rate = frames / max(0.001, time.time() - started)
                print(f"published {frames} frames ({rate:.1f} fps)", flush=True)
            stream.wait_for_next_frame()
    finally:
        if capture is not None:
            capture.release()
        if picamera is not None:
            picamera.stop()
            picamera.close()
        stream.close()

    print(f"stopped after {frames} frames ({stream.errors} send errors)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
