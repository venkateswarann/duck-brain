"""Example camera script node for DCS.

Replace with a wrapper around Open_Duck_Mini_Runtime camera helpers when hardware is available.
"""

from __future__ import annotations

import signal
import sys
import time


running = True


def _stop(*_args):
    global running
    running = False


def main() -> int:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    print("[camera] started (placeholder — no capture device required)")
    ticks = 0
    while running:
        ticks += 1
        if ticks % 10 == 0:
            print(f"[camera] heartbeat frames={ticks}")
        time.sleep(0.5)
    print("[camera] stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
