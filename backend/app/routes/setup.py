"""Setup routes: servo ID management and joint offset calibration."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..config_loader import DEFAULT_CONFIG, save_json
from ..services.servo_setup import ServoSetupService

router = APIRouter(prefix="/api/setup", tags=["setup"])

# Single service instance — created lazily on first use per-app.
_service: ServoSetupService | None = None


def _get_service(request: Request) -> ServoSetupService:
    global _service
    if _service is None:
        mock = request.app.state.duck.mock_hardware
        _service = ServoSetupService(mock=mock)
    return _service


def _joints(request: Request):
    """Get joints dict from current config."""
    return request.app.state.duck.joints


def _port(request: Request) -> str:
    return request.app.state.duck.serial_port


def _baudrate(request: Request) -> int:
    return request.app.state.duck.baudrate


# ── Servo ID Management ──────────────────────────────────────────────


@router.post("/servo/scan")
async def servo_scan(request: Request):
    """Scan the servo bus for all responding IDs."""
    svc = _get_service(request)
    try:
        found = svc.scan_bus(_port(request), _baudrate(request))
        return {"ok": True, "servos": found, "count": len(found)}
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@router.post("/servo/set-id")
async def servo_set_id(request: Request):
    """Change a servo's ID.

    Body: {current_id: int, new_id: int}
    """
    body = await request.json()
    current_id = int(body.get("current_id", 0))
    new_id = int(body.get("new_id", 0))
    if not current_id or not new_id:
        raise HTTPException(400, "current_id and new_id are required")
    if new_id < 1 or new_id > 253:
        raise HTTPException(400, "new_id must be 1–253")

    svc = _get_service(request)
    try:
        result = svc.set_servo_id(_port(request), current_id, new_id, _baudrate(request))
        return result
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/servo/status")
async def servo_status(request: Request):
    """Check if all expected servos respond on the bus."""
    svc = _get_service(request)
    try:
        status = svc.get_servo_status(_port(request), _joints(request), _baudrate(request))
        all_online = all(s["online"] for s in status)
        return {"ok": True, "joints": status, "all_online": all_online}
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


# ── Joint Offset Calibration ─────────────────────────────────────────


@router.post("/calibration/start")
async def calibration_start(request: Request):
    """Begin a calibration session. Pauses motors.telemetry to free the serial bus."""
    svc = _get_service(request)
    if svc.session.active:
        raise HTTPException(409, "Calibration session already active")

    # Pause motors.telemetry if running
    registry = request.app.state.registry
    motors_node = registry.get_optional("motors.telemetry")
    if motors_node and motors_node.state.value == "running":
        await registry.stop("motors.telemetry")

    try:
        result = svc.start_calibration(_port(request), _joints(request), _baudrate(request))
        return result
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@router.post("/calibration/stop")
async def calibration_stop(request: Request):
    """End the calibration session and optionally restart motors.telemetry."""
    svc = _get_service(request)
    result = svc.stop_calibration()

    # Restart motors.telemetry
    registry = request.app.state.registry
    motors_node = registry.get_optional("motors.telemetry")
    if motors_node and motors_node.state.value != "running":
        try:
            await registry.start("motors.telemetry")
        except Exception:
            pass  # Best effort

    return result


@router.get("/calibration/status")
async def calibration_status(request: Request):
    """Get the current calibration session state."""
    svc = _get_service(request)
    return svc.get_calibration_status()


@router.post("/calibration/move-to-zero")
async def calibration_move_to_zero(request: Request):
    """Move all joints to their zero position."""
    svc = _get_service(request)
    if not svc.session.active:
        raise HTTPException(409, "No active calibration session")
    try:
        return svc.move_to_zero(_joints(request))
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@router.post("/calibration/joint/disable-torque")
async def calibration_disable_torque(request: Request):
    """Disable torque on a specific joint so user can move it by hand.

    Body: {joint_name: str}
    """
    svc = _get_service(request)
    if not svc.session.active:
        raise HTTPException(409, "No active calibration session")
    body = await request.json()
    joint_name = body.get("joint_name", "")
    if not joint_name:
        raise HTTPException(400, "joint_name required")
    try:
        return svc.disable_joint_torque(joint_name, _joints(request))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/calibration/joint/enable-torque")
async def calibration_enable_torque(request: Request):
    """Re-enable torque on a specific joint.

    Body: {joint_name: str}
    """
    svc = _get_service(request)
    if not svc.session.active:
        raise HTTPException(409, "No active calibration session")
    body = await request.json()
    joint_name = body.get("joint_name", "")
    if not joint_name:
        raise HTTPException(400, "joint_name required")
    try:
        return svc.enable_joint_torque(joint_name, _joints(request))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/calibration/joint/read-position")
async def calibration_read_position(request: Request):
    """Read the current position of a joint in radians.

    Body: {joint_name: str}
    """
    svc = _get_service(request)
    if not svc.session.active:
        raise HTTPException(409, "No active calibration session")
    body = await request.json()
    joint_name = body.get("joint_name", "")
    if not joint_name:
        raise HTTPException(400, "joint_name required")
    try:
        return svc.read_joint_position(joint_name, _joints(request))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/calibration/joint/goto-zero")
async def calibration_goto_zero(request: Request):
    """Move a joint to zero with offset applied.

    Body: {joint_name: str, offset: float}
    """
    svc = _get_service(request)
    if not svc.session.active:
        raise HTTPException(409, "No active calibration session")
    body = await request.json()
    joint_name = body.get("joint_name", "")
    offset = float(body.get("offset", 0.0))
    if not joint_name:
        raise HTTPException(400, "joint_name required")
    try:
        return svc.goto_zero_with_offset(joint_name, offset, _joints(request))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/calibration/joint/set-offset")
async def calibration_set_offset(request: Request):
    """Record the calibrated offset for a joint.

    Body: {joint_name: str, offset: float}
    """
    svc = _get_service(request)
    if not svc.session.active:
        raise HTTPException(409, "No active calibration session")
    body = await request.json()
    joint_name = body.get("joint_name", "")
    offset = float(body.get("offset", 0.0))
    if not joint_name:
        raise HTTPException(400, "joint_name required")
    return svc.set_joint_offset(joint_name, offset)


@router.post("/calibration/joint/skip")
async def calibration_skip_joint(request: Request):
    """Skip calibration for a joint.

    Body: {joint_name: str}
    """
    svc = _get_service(request)
    if not svc.session.active:
        raise HTTPException(409, "No active calibration session")
    body = await request.json()
    joint_name = body.get("joint_name", "")
    if not joint_name:
        raise HTTPException(400, "joint_name required")
    return svc.skip_joint(joint_name)


@router.post("/calibration/save")
async def calibration_save(request: Request):
    """Write the calibrated offsets to duck_config.json."""
    svc = _get_service(request)
    offsets = svc.session.offsets
    if not offsets:
        raise HTTPException(400, "No offsets recorded")

    # Merge offsets into current config
    cfg = request.app.state.duck
    merged = dict(cfg.joints_offsets)
    for name, val in offsets.items():
        if val != 0.0 or name not in merged:
            merged[name] = val

    # Update config
    from ..schemas import DuckConfig
    data = cfg.model_dump()
    data["joints_offsets"] = merged
    try:
        new_cfg = DuckConfig.model_validate(data)
    except Exception as exc:
        raise HTTPException(400, f"Invalid config: {exc}") from exc

    path = getattr(request.app.state, "config_path", DEFAULT_CONFIG)
    if path.name.endswith(".example.json"):
        path = DEFAULT_CONFIG
        request.app.state.config_path = path
    save_json(path, new_cfg.model_dump())
    request.app.state.duck = new_cfg

    return {
        "ok": True,
        "path": str(path),
        "joints_offsets": merged,
        "note": "Offsets saved to duck_config.json",
    }


@router.post("/calibration/emergency-stop")
async def calibration_emergency_stop(request: Request):
    """Disable torque on ALL joints immediately. Safety endpoint."""
    svc = _get_service(request)
    try:
        result = svc.emergency_stop(_joints(request))
        return result
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc
