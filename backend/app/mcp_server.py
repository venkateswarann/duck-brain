"""MCP (Model Context Protocol) server integration for DCS.

Exposes DCS API endpoints as MCP tools for AI model access.
Two modes:
  - Default (read-only): only safe, read-only endpoints exposed
  - Dev mode (mcp_dev_mode=true in config): all endpoints including
    dangerous operations (config writes, script execution, servo control)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)

# Read-only operations always exposed (by route function name; setup_mcp
# turns these into operation ids)
_READ_ONLY_OPS = [
    "health",
    "get_config",
    "list_motors",
    "system_snapshot",
    "get_pinout",
    "export_pinout",
    "list_scripts",
    "scripts_tree",
    "scripts_templates",
    "read_script",
    "get_robot_model",
    "get_robot_urdf",
    "get_robot_asset",
    "help_bundle",
    "list_boards",
    "keymap",
    "network_settings",
    "bluetooth_status",
    "bluetooth_devices",
    "servo_status",
    "calibration_status",
    "get_all_logs",
]

# Companion (Duck Brain) tools, always exposed: every one is clamped,
# rate-limited and logged server-side, so they are safe without dev mode.
_COMPANION_OPS = [
    "head_look_at",
    "head_nod",
    "head_shake",
    "head_tilt",
    "head_center",
    "head_stop",
    "head_state",
    "head_idle_motion",
    "eyes_list_expressions",
    "eyes_set_expression",
    "eyes_look",
    "eyes_blink",
    "eyes_idle",
    "eyes_state",
    "speech_say",
    "speech_stop",
    "estop",
    "companion_status",
]

# Additional operations exposed in mcp_dev_mode
_DEV_MODE_OPS = [
    "put_config",
    "put_pinout",
    "import_pinout",
    "run_script",
    "stop_script",
    "write_script",
    "create_script",
    "create_script_folder",
    "rename_script",
    "delete_script",
    "bluetooth_scan",
    "bluetooth_power",
    "bluetooth_pair",
    "bluetooth_connect",
    "bluetooth_disconnect",
    "bluetooth_remove",
    "servo_scan",
    "servo_set_id",
    "calibration_start",
    "calibration_stop",
    "calibration_move_to_zero",
    "calibration_disable_torque",
    "calibration_enable_torque",
    "calibration_read_position",
    "calibration_goto_zero",
    "calibration_set_offset",
    "calibration_skip_joint",
    "calibration_save",
    "calibration_emergency_stop",
]


def setup_mcp(app: "FastAPI") -> None:
    """Set up the MCP server and mount it on the FastAPI app at /mcp."""
    try:
        from fastapi_mcp import FastApiMCP  # type: ignore
    except ImportError:
        logger.warning(
            "fastapi-mcp not installed — MCP server disabled. "
            "Install with: pip install fastapi-mcp"
        )
        return

    duck = getattr(app.state, "duck", None)
    is_dev = bool(getattr(duck, "mcp_dev_mode", False))
    allowed = list(_READ_ONLY_OPS) + list(_COMPANION_OPS)
    if is_dev:
        allowed.extend(_DEV_MODE_OPS)

    # The lists above use function names, but FastAPI's generated operation ids
    # look like "health_api_health_get", so without this none of them matched.
    # Must run before the OpenAPI schema is first built (and cached).
    from fastapi.routing import APIRoute

    def walk(routes):
        # Newer FastAPI nests included routers instead of flattening them.
        for item in routes:
            if isinstance(item, APIRoute):
                yield item
            elif getattr(item, "original_router", None) is not None:  # FastAPI >= 0.13x
                yield from walk(item.original_router.routes)
            elif getattr(item, "router", None) is not None:
                yield from walk(item.router.routes)
            elif getattr(item, "routes", None):
                yield from walk(item.routes)

    wanted = set(allowed)
    by_name: dict[str, APIRoute] = {}
    for route in walk(app.routes):
        if route.operation_id is None and route.name in wanted:
            # Same function name in two routers (e.g. get_config): the shorter,
            # top-level path is the one the list means.
            if route.name not in by_name or len(route.path) < len(by_name[route.name].path):
                by_name[route.name] = route
    for name, route in by_name.items():
        route.operation_id = name

    try:
        mcp = FastApiMCP(
            app,
            name="DCS Robot Control",
            description=(
                "Duck Control System — robot management API for AI agents. "
                + "Companion tools (head, eyes, speech, estop) are always on and clamped server-side. "
                + ("DEV MODE: write operations enabled." if is_dev else "Admin operations are read-only.")
            ),
            include_operations=allowed,
        )
        # Prefer Streamable HTTP; fall back for older fastapi-mcp versions.
        if hasattr(mcp, "mount_http"):
            mcp.mount_http(mount_path="/mcp")
        elif hasattr(mcp, "mount"):
            mcp.mount()
        else:
            raise RuntimeError("FastApiMCP has no mount_http/mount method")

        mode_label = "DEV (write ops)" if is_dev else "READ-ONLY"
        logger.info("MCP server mounted at /mcp — mode: %s (%d tools)", mode_label, len(allowed))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to set up MCP server: %s", exc)
