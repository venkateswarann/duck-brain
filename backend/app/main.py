from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config_loader import (
    BOARDS_DIR,
    DEFAULT_CONFIG,
    DEFAULT_PINOUT,
    EXAMPLE_CONFIG,
    load_duck_config,
    load_json,
    load_script_manifest,
)
from .nodes.gpio_node import GpioPinsNode
from .nodes.motors_telemetry import MotorsTelemetryNode
from .nodes.script_node import discover_script_nodes
from .nodes.system_metrics import SystemMetricsNode
from .nodes.video_capture import VideoCaptureNode
from .routes import api as api_routes
from .routes import gpio as gpio_routes
from .routes import nodes as nodes_routes
from .routes import setup as setup_routes
from .routes import terminal as terminal_routes
from .routes import video as video_routes
from .runtime.bus import TelemetryBus
from .services.frame_hub import FrameHub
from .services.script_fs import ScriptFsError
from .runtime.locks import ResourceLocks
from .runtime.registry import NodeRegistry


class AppState:
    def __init__(self) -> None:
        self.config_path = DEFAULT_CONFIG if DEFAULT_CONFIG.exists() else EXAMPLE_CONFIG
        self.duck = load_duck_config(self.config_path)
        self.bus = TelemetryBus()
        self.locks = ResourceLocks()
        self.registry = NodeRegistry(self.bus, self.locks)
        self.frames = FrameHub()
        pinout_live = DEFAULT_CONFIG.parent / "pinout_schema.json"
        self.pinout_path = pinout_live if pinout_live.exists() else DEFAULT_PINOUT
        self.pinout = load_json(self.pinout_path) or {
            "schema_version": 1,
            "board": "rpi5",
            "devices": [],
        }
        self.boards_dir = BOARDS_DIR


@asynccontextmanager
async def lifespan(app: FastAPI):
    state: AppState = app.state
    # Register core nodes
    state.registry.register(
        MotorsTelemetryNode(state.bus, state.locks, state.duck)
    )
    state.registry.register(VideoCaptureNode(state.bus, state.locks, config=state.duck))
    state.registry.register(SystemMetricsNode(state.bus, state.locks))
    state.registry.register(
        GpioPinsNode(
            state.bus, state.locks,
            mock=state.duck.mock_hardware,
            pinout=state.pinout,
        )
    )
    for sn in discover_script_nodes(
        state.bus, state.locks, load_script_manifest()
    ):
        state.registry.register(sn)

    enabled = dict(state.duck.nodes)
    # Auto-start gpio.pins when devices exist in pinout
    if state.pinout.get("devices"):
        enabled.setdefault("gpio.pins", True)
    # Don't auto-start scripts
    await state.registry.start_enabled(enabled)
    yield
    for info in state.registry.list():
        try:
            await state.registry.stop(info.id)
        except Exception:  # noqa: BLE001
            pass


def create_app() -> FastAPI:
    app = FastAPI(title="DCS — Duck Control System", version="0.1.0", lifespan=lifespan)
    app.state = AppState()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_routes.router)
    app.include_router(gpio_routes.router)
    app.include_router(nodes_routes.router)
    app.include_router(setup_routes.router)
    app.include_router(terminal_routes.router)
    app.include_router(video_routes.router)

    # MCP server (Model Context Protocol for AI agents)
    from .mcp_server import setup_mcp
    setup_mcp(app)

    @app.exception_handler(ScriptFsError)
    async def script_fs_error(_request: Request, exc: ScriptFsError):
        return JSONResponse({"detail": exc.message}, status_code=exc.status)

    @app.get("/")
    async def root():
        return {
            "name": "DCS",
            "docs": "/docs",
            "health": "/api/health",
        }

    return app


app = create_app()
