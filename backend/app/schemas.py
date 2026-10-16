from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class NodeState(str, Enum):
    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


class RangeScale(BaseModel):
    min: float
    max: float


class JointConfig(BaseModel):
    id: int
    min: float
    max: float
    unit: str = "rad"


class HeadJointLimit(BaseModel):
    min_deg: float
    max_deg: float


def _default_head_limits() -> dict[str, HeadJointLimit]:
    # Safe ranges from robot_scripts/head_puppet.py, tighter than the URDF limits.
    return {
        "head_yaw": HeadJointLimit(min_deg=-60, max_deg=60),
        "head_pitch": HeadJointLimit(min_deg=-60, max_deg=45),
        "head_roll": HeadJointLimit(min_deg=-20, max_deg=20),
        "neck_pitch": HeadJointLimit(min_deg=-20, max_deg=60),
    }


class AudioConfig(BaseModel):
    mic_device: Optional[int | str] = None  # sounddevice name/index; None = default
    speaker_device: Optional[int | str] = None
    sample_rate: int = 16000
    vad_aggressiveness: int = 2  # webrtcvad 0-3
    silence_ms: int = 700  # end an utterance after this much silence
    max_utterance_s: float = 15.0
    piper_voice: str = ""  # path to a Piper .onnx voice; empty = no TTS


class IdleMotionConfig(BaseModel):
    """Breathing-style idle motion layered on the head pose (off until enabled at runtime)."""

    breath_deg: float = 1.5  # pitch amplitude of the "breath"
    breath_hz: float = 0.22  # ~13 breaths a minute
    sway_deg: float = 2.0  # slow wandering in yaw (roll gets half)


class CompanionConfig(BaseModel):
    """Head, eyes and audio for the desk-companion (Duck Brain) mode."""

    eyes_urls: list[str] = Field(default_factory=lambda: ["http://10.55.0.2:8100"])
    head_limits: dict[str, HeadJointLimit] = Field(default_factory=_default_head_limits)
    max_vel_dps: float = 60.0  # head joint speed cap, degrees per second
    max_acc_dps2: float = 240.0  # acceleration cap: moves ease in and out, no jerks
    response_s: float = 0.45  # how quickly the head settles on a new target
    control_hz: float = 50.0
    head_kp: int = 8
    cmd_rate_hz: float = 10.0  # head commands accepted per second (excess are rejected)
    gesture_max_times: int = 3
    hold_timeout_s: float = 20.0  # an off-centre pose drifts back to centre after this
    camera_stream: str = "head_cam"
    idle_motion: IdleMotionConfig = Field(default_factory=IdleMotionConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)


class DuckConfig(BaseModel):
    robot_id: str = "duck-mini-001"
    robot_name: str = "Open Duck Mini"
    serial_port: str = "/dev/ttyACM0"
    baudrate: int = 1_000_000
    poll_hz: float = 15.0
    mock_hardware: bool = True
    camera_device: int | str = 0
    camera_width: int = 640
    camera_height: int = 480
    camera_rotation: int = 0
    camera_fps: int = 15
    camera_flip_h: bool = False
    camera_flip_v: bool = False
    camera_swap_rb: bool = False
    serial_policy: str = "prefer_script"
    joints: dict[str, JointConfig] = Field(default_factory=dict)
    joints_offsets: dict[str, float] = Field(default_factory=dict)
    telemetry_scales: dict[str, RangeScale] = Field(default_factory=dict)
    nodes: dict[str, bool] = Field(default_factory=dict)
    control: dict[str, Any] = Field(default_factory=dict)
    allow_script_runner: bool = True
    allow_web_terminal: bool = False
    mcp_dev_mode: bool = False
    llm_provider: str = "nvidia"
    llm_endpoint: str = "https://integrate.api.nvidia.com/v1"
    llm_api_key: str = ""
    llm_model: str = "nvidia/nemotron-3-ultra-550b-a55b"
    llm_temperature: float = 0.7
    llm_max_tokens: int = 8192
    companion: CompanionConfig = Field(default_factory=CompanionConfig)


class NodeInfo(BaseModel):
    id: str
    name: str
    kind: str
    state: NodeState
    pid: Optional[int] = None
    cpu_percent: float = 0.0
    memory_mib: float = 0.0
    open_files: int = 0
    host: str = "localhost"
    error: Optional[str] = None
    resources: list[str] = Field(default_factory=list)
    topics_out: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)


class MotorTelemetry(BaseModel):
    id: int
    name: str
    position: float = 0.0
    position_raw: Optional[int] = None
    temperature_c: float = 0.0
    voltage_v: float = 0.0
    current_ma: float = 0.0
    load: float = 0.0
    speed: float = 0.0
    online: bool = True
    status: dict[str, bool] = Field(default_factory=dict)


class TelemetrySnapshot(BaseModel):
    ts: float
    motors: dict[str, MotorTelemetry] = Field(default_factory=dict)
    nodes: dict[str, NodeState] = Field(default_factory=dict)
    system: dict[str, Any] = Field(default_factory=dict)
    video: dict[str, Any] = Field(default_factory=dict)
