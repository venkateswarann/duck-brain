"""Example RL walk script node for DCS.

Wire this to Open_Duck_Mini_Runtime scripts/v2_rl_walk_mujoco.py on the robot.
Owns the serial resource while running (MotorsTelemetry pauses).
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
    print("[rl_walk] started (placeholder — no serial writes)")
    print("[rl_walk] Replace body with Open Duck Mini Runtime walk loop")
    ticks = 0
    while running:
        ticks += 1
        if ticks % 20 == 0:
            print(f"[rl_walk] step={ticks}")
        time.sleep(0.1)
    print("[rl_walk] stopped — serial lock will be released by DCS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
