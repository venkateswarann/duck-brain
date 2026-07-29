from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schemas import DuckConfig, JointConfig, RangeScale

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "configs" / "duck_config.json"
EXAMPLE_CONFIG = ROOT / "configs" / "duck_config.example.json"
DEFAULT_PINOUT = ROOT / "configs" / "pinout_schema.example.json"
SCRIPTS_DIR = ROOT / "robot_scripts"
ASSETS_DIR = ROOT / "assets"
BOARDS_DIR = Path(__file__).resolve().parent / "boards"


def _default_joints() -> dict[str, JointConfig]:
    # IDs from Open_Duck_Mini_Runtime rustypot_position_hwi.py
    spec = {
        "right_hip_yaw": 10,
        "right_hip_roll": 11,
        "right_hip_pitch": 12,
        "right_knee": 13,
        "right_ankle": 14,
        "left_hip_yaw": 20,
        "left_hip_roll": 21,
        "left_hip_pitch": 22,
        "left_knee": 23,
        "left_ankle": 24,
        "neck_pitch": 30,
        "head_pitch": 31,
        "head_yaw": 32,
        "head_roll": 33,
    }
    return {
        name: JointConfig(id=jid, min=-1.5, max=1.5, unit="rad")
        for name, jid in spec.items()
    }


def load_duck_config(path: Path | None = None) -> DuckConfig:
    cfg_path = path or (DEFAULT_CONFIG if DEFAULT_CONFIG.exists() else EXAMPLE_CONFIG)
    if not cfg_path.exists():
        return DuckConfig(
            joints=_default_joints(),
            telemetry_scales={
                "temperature_c": RangeScale(min=0, max=80),
                "voltage_v": RangeScale(min=4.0, max=8.5),
                "current_ma": RangeScale(min=0, max=3000),
                "load": RangeScale(min=-1024, max=1023),
                "speed": RangeScale(min=-3400, max=3400),
            },
        )
    data = json.loads(cfg_path.read_text())
    return DuckConfig.model_validate(data)


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def load_script_manifest() -> dict[str, Any]:
    return load_json(SCRIPTS_DIR / "manifest.json")
