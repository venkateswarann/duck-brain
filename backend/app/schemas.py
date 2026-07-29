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


class DuckConfig(BaseModel):
    robot_id: str = "duck-mini-001"
    robot_name: str = "Open Duck Mini"
    serial_port: str = "/dev/ttyACM0"
    baudrate: int = 1_000_000
    poll_hz: float = 15.0
    mock_hardware: bool = True
    serial_policy: str = "prefer_script"
    joints: dict[str, JointConfig] = Field(default_factory=dict)
    joints_offsets: dict[str, float] = Field(default_factory=dict)
    telemetry_scales: dict[str, RangeScale] = Field(default_factory=dict)
    nodes: dict[str, bool] = Field(default_factory=dict)
    control: dict[str, Any] = Field(default_factory=dict)
    allow_script_runner: bool = True
    allow_web_terminal: bool = False


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
