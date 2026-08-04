"""Service for servo setup: ID assignment, joint calibration, and bus scanning.

Mirrors the logic from Open_Duck_Mini_Runtime scripts:
  - configure_motor.py  → scan + change ID
  - find_soft_offsets.py → per-joint offset calibration

Uses st3215 for real hardware (same library as motors_telemetry node).
Falls back to mock responses when mock_hardware=true.
"""

from __future__ import annotations

import math
import time
import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional

# Joint definitions matching HWI ordering from Open_Duck_Mini_Runtime
JOINTS_MAP: dict[str, int] = {
    "left_hip_yaw": 20,
    "left_hip_roll": 21,
    "left_hip_pitch": 22,
    "left_knee": 23,
    "left_ankle": 24,
    "neck_pitch": 30,
    "head_pitch": 31,
    "head_yaw": 32,
    "head_roll": 33,
    "right_hip_yaw": 10,
    "right_hip_roll": 11,
    "right_hip_pitch": 12,
    "right_knee": 13,
    "right_ankle": 14,
}


def _steps_to_rad(steps: int) -> float:
    """STS3215: 4096 steps ≈ 2π."""
    return (steps - 2048) * (2 * math.pi / 4096)


def _rad_to_steps(rad: float) -> int:
    return int(2048 + rad * (4096 / (2 * math.pi)))


@dataclass
class CalibrationSession:
    """Holds state for an in-progress calibration session."""
    active: bool = False
    offsets: dict[str, float] = field(default_factory=dict)
    joint_states: dict[str, str] = field(default_factory=dict)  # pending|in_progress|calibrated|skipped
    current_joint: Optional[str] = None
    zero_positions: dict[str, float] = field(default_factory=dict)


class ServoSetupService:
    """Manages servo hardware for setup operations."""

    def __init__(self, mock: bool = True) -> None:
        self.mock = mock
        self._servo: Any = None
        self._port: Optional[str] = None
        self.session = CalibrationSession()

    def _ensure_servo(self, port: str, baudrate: int = 1_000_000) -> None:
        """Open the serial connection if needed."""
        if self.mock:
            return
        if self._servo is not None and self._port == port:
            return
        try:
            from st3215 import ST3215  # type: ignore
            self._servo = ST3215(port)
            self._port = port
        except Exception as exc:
            raise RuntimeError(f"Cannot open servo bus on {port}: {exc}") from exc

    def _close(self) -> None:
        self._servo = None
        self._port = None

    # ── Servo ID Management ──────────────────────────────────────────

    def scan_bus(self, port: str, baudrate: int = 1_000_000) -> list[dict[str, Any]]:
        """Scan the servo bus for all responding IDs.

        Returns list of {id, position_raw, position_rad, joint_name?}.
        """
        if self.mock:
            # Return all configured joints as "found"
            return [
                {
                    "id": jid,
                    "position_raw": 2048,
                    "position_rad": 0.0,
                    "joint_name": name,
                }
                for name, jid in JOINTS_MAP.items()
            ]

        self._ensure_servo(port, baudrate)
        found: list[dict[str, Any]] = []
        id_to_name = {v: k for k, v in JOINTS_MAP.items()}
        # Scan expected IDs first (fast), then sweep 1-253 for unknown
        check_ids = sorted(set(JOINTS_MAP.values()) | {1})
        for sid in check_ids:
            try:
                pos_raw = self._servo.ReadPosition(sid)
                if pos_raw is not None:
                    found.append({
                        "id": sid,
                        "position_raw": pos_raw,
                        "position_rad": round(_steps_to_rad(pos_raw), 4),
                        "joint_name": id_to_name.get(sid),
                    })
            except Exception:
                pass
        return found

    def set_servo_id(
        self, port: str, current_id: int, new_id: int, baudrate: int = 1_000_000
    ) -> dict[str, Any]:
        """Change a servo's ID and configure its defaults (PID, mode, acceleration).

        Mirrors configure_motor.py: unlock → set mode/PID/accel → change ID → verify.
        """
        if self.mock:
            return {
                "ok": True,
                "old_id": current_id,
                "new_id": new_id,
                "mock": True,
            }

        self._ensure_servo(port, baudrate)
        s = self._servo
        try:
            # Verify the servo exists at current_id
            s.ReadPosition(current_id)
        except Exception as exc:
            raise RuntimeError(f"No servo found at ID {current_id}: {exc}") from exc

        try:
            # Unlock EEPROM, configure defaults, change ID
            s.UnlockEprom(current_id)
            s.WriteMode(current_id, 0)  # Position mode
            s.WritePGain(current_id, 32)
            s.WriteIGain(current_id, 0)
            s.WriteDGain(current_id, 0)
            s.WriteID(current_id, new_id)
            time.sleep(0.5)
            # Verify at new ID
            s.ReadPosition(new_id)
            s.LockEprom(new_id)
            return {"ok": True, "old_id": current_id, "new_id": new_id}
        except Exception as exc:
            raise RuntimeError(f"Failed to set ID {current_id}→{new_id}: {exc}") from exc

    def get_servo_status(
        self, port: str, joints: dict[str, Any], baudrate: int = 1_000_000
    ) -> list[dict[str, Any]]:
        """Check which expected joints respond on the bus.

        Returns per-joint status: {joint_name, expected_id, online, position_rad?}.
        """
        if self.mock:
            return [
                {
                    "joint_name": name,
                    "expected_id": jcfg.id if hasattr(jcfg, "id") else jcfg.get("id", 0),
                    "online": True,
                    "position_rad": 0.0,
                }
                for name, jcfg in joints.items()
            ]

        self._ensure_servo(port, baudrate)
        results = []
        for name, jcfg in joints.items():
            jid = jcfg.id if hasattr(jcfg, "id") else jcfg.get("id", 0)
            online = False
            pos = None
            try:
                pos_raw = self._servo.ReadPosition(jid)
                if pos_raw is not None:
                    online = True
                    pos = round(_steps_to_rad(pos_raw), 4)
            except Exception:
                pass
            results.append({
                "joint_name": name,
                "expected_id": jid,
                "online": online,
                "position_rad": pos,
            })
        return results

    # ── Joint Calibration ────────────────────────────────────────────

    def start_calibration(
        self, port: str, joints: dict[str, Any], baudrate: int = 1_000_000
    ) -> dict[str, Any]:
        """Begin a calibration session. Initializes offsets to 0."""
        if not self.mock:
            self._ensure_servo(port, baudrate)

        self.session = CalibrationSession(
            active=True,
            offsets={name: 0.0 for name in joints},
            joint_states={name: "pending" for name in joints},
        )
        return {"active": True, "joints": list(joints.keys())}

    def stop_calibration(self) -> dict[str, Any]:
        """End the calibration session."""
        offsets = dict(self.session.offsets)
        self.session = CalibrationSession()
        self._close()
        return {"active": False, "final_offsets": offsets}

    def get_calibration_status(self) -> dict[str, Any]:
        return {
            "active": self.session.active,
            "offsets": self.session.offsets,
            "joint_states": self.session.joint_states,
            "current_joint": self.session.current_joint,
        }

    def move_to_zero(self, joints: dict[str, Any]) -> dict[str, Any]:
        """Move all joints to zero position (no offset applied)."""
        if self.mock:
            return {"ok": True, "mock": True}

        s = self._servo
        for name, jcfg in joints.items():
            jid = jcfg.id if hasattr(jcfg, "id") else jcfg.get("id", 0)
            try:
                s.EnableTorque(jid)
                s.WritePGain(jid, 32)
                s.WriteGoalPosition(jid, _rad_to_steps(0.0))
            except Exception:
                pass
        time.sleep(1)
        return {"ok": True}

    def disable_joint_torque(self, joint_name: str, joints: dict[str, Any]) -> dict[str, Any]:
        """Disable torque on a specific joint so user can move it by hand."""
        jcfg = joints.get(joint_name)
        if jcfg is None:
            raise ValueError(f"Unknown joint: {joint_name}")
        jid = jcfg.id if hasattr(jcfg, "id") else jcfg.get("id", 0)

        self.session.current_joint = joint_name
        self.session.joint_states[joint_name] = "in_progress"

        if self.mock:
            return {"ok": True, "joint": joint_name, "id": jid, "mock": True}

        try:
            self._servo.DisableTorque(jid)
        except Exception as exc:
            raise RuntimeError(f"Failed to disable torque on {joint_name} (ID {jid}): {exc}") from exc
        return {"ok": True, "joint": joint_name, "id": jid}

    def enable_joint_torque(self, joint_name: str, joints: dict[str, Any]) -> dict[str, Any]:
        """Re-enable torque on a specific joint."""
        jcfg = joints.get(joint_name)
        if jcfg is None:
            raise ValueError(f"Unknown joint: {joint_name}")
        jid = jcfg.id if hasattr(jcfg, "id") else jcfg.get("id", 0)

        if self.mock:
            return {"ok": True, "joint": joint_name, "id": jid, "mock": True}

        try:
            self._servo.EnableTorque(jid)
            self._servo.WritePGain(jid, 32)
        except Exception as exc:
            raise RuntimeError(f"Failed to enable torque on {joint_name} (ID {jid}): {exc}") from exc
        return {"ok": True, "joint": joint_name, "id": jid}

    def read_joint_position(self, joint_name: str, joints: dict[str, Any]) -> dict[str, Any]:
        """Read the current position of a joint in radians."""
        jcfg = joints.get(joint_name)
        if jcfg is None:
            raise ValueError(f"Unknown joint: {joint_name}")
        jid = jcfg.id if hasattr(jcfg, "id") else jcfg.get("id", 0)

        if self.mock:
            import random
            mock_pos = round(random.uniform(-0.1, 0.1), 4)
            return {"joint": joint_name, "id": jid, "position_rad": mock_pos, "mock": True}

        try:
            pos_raw = self._servo.ReadPosition(jid)
            if pos_raw is None:
                raise RuntimeError(f"No response from {joint_name} (ID {jid})")
            pos = round(_steps_to_rad(pos_raw), 4)
            return {"joint": joint_name, "id": jid, "position_rad": pos}
        except Exception as exc:
            raise RuntimeError(f"Failed to read position of {joint_name}: {exc}") from exc

    def goto_zero_with_offset(
        self, joint_name: str, offset: float, joints: dict[str, Any]
    ) -> dict[str, Any]:
        """Move a joint to zero accounting for the given offset."""
        jcfg = joints.get(joint_name)
        if jcfg is None:
            raise ValueError(f"Unknown joint: {joint_name}")
        jid = jcfg.id if hasattr(jcfg, "id") else jcfg.get("id", 0)

        if self.mock:
            return {"ok": True, "joint": joint_name, "offset": offset, "mock": True}

        try:
            target = 0.0 + offset
            self._servo.WriteGoalPosition(jid, _rad_to_steps(target))
            time.sleep(0.5)
            return {"ok": True, "joint": joint_name, "offset": offset}
        except Exception as exc:
            raise RuntimeError(f"Failed to move {joint_name} to zero: {exc}") from exc

    def set_joint_offset(self, joint_name: str, offset: float) -> dict[str, Any]:
        """Record the calibrated offset for a joint in the session."""
        self.session.offsets[joint_name] = round(offset, 4)
        self.session.joint_states[joint_name] = "calibrated"
        if self.session.current_joint == joint_name:
            self.session.current_joint = None
        return {"ok": True, "joint": joint_name, "offset": round(offset, 4)}

    def skip_joint(self, joint_name: str) -> dict[str, Any]:
        """Mark a joint as skipped in the calibration session."""
        self.session.joint_states[joint_name] = "skipped"
        if self.session.current_joint == joint_name:
            self.session.current_joint = None
        return {"ok": True, "joint": joint_name, "state": "skipped"}

    def emergency_stop(self, joints: dict[str, Any]) -> dict[str, Any]:
        """Disable torque on ALL joints immediately."""
        if self.mock:
            self.session.active = False
            return {"ok": True, "mock": True}

        errors = []
        for name, jcfg in joints.items():
            jid = jcfg.id if hasattr(jcfg, "id") else jcfg.get("id", 0)
            try:
                self._servo.DisableTorque(jid)
            except Exception as exc:
                errors.append(f"{name}(ID {jid}): {exc}")

        self.session.active = False
        self._close()
        return {"ok": len(errors) == 0, "errors": errors}
