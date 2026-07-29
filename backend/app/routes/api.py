from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from ..config_loader import ASSETS_DIR, ROOT, SCRIPTS_DIR, load_script_manifest, save_json
from ..nodes.script_node import ScriptNode, discover_script_nodes

router = APIRouter(tags=["api"])


@router.get("/api/health")
async def health(request: Request):
    return {
        "ok": True,
        "robot_id": request.app.state.duck.robot_id,
        "robot_name": request.app.state.duck.robot_name,
        "locks": request.app.state.locks.snapshot(),
    }


@router.get("/api/config")
async def get_config(request: Request):
    return request.app.state.duck.model_dump()


@router.put("/api/config")
async def put_config(request: Request):
    """Save duck_config.json and hot-apply safe fields."""
    from ..config_loader import DEFAULT_CONFIG, save_json
    from ..schemas import DuckConfig

    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(400, "Expected JSON object")
    try:
        cfg = DuckConfig.model_validate(body)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Invalid config: {exc}") from exc

    path = getattr(request.app.state, "config_path", DEFAULT_CONFIG)
    if path.name.endswith(".example.json"):
        path = DEFAULT_CONFIG
        request.app.state.config_path = path
    save_json(path, cfg.model_dump())
    request.app.state.duck = cfg

    motors = request.app.state.registry.get_optional("motors.telemetry")
    if motors is not None:
        motors.duck = cfg  # type: ignore[attr-defined]
        await motors.set_config(
            {
                "serial_port": cfg.serial_port,
                "baudrate": cfg.baudrate,
                "poll_hz": cfg.poll_hz,
                "mock_hardware": cfg.mock_hardware,
            }
        )

    return {
        "ok": True,
        "path": str(path),
        "config": cfg.model_dump(),
        "note": "Saved. Restart motors.telemetry if you changed mock_hardware or serial_port while it was running.",
    }


@router.get("/api/robot/urdf")
async def get_robot_urdf():
    candidates = [
        ASSETS_DIR / "robot.urdf",
        ROOT / "assets" / "robot.urdf",
        Path.cwd() / "assets" / "robot.urdf",
        Path.cwd().parent / "assets" / "robot.urdf",
        Path(__file__).resolve().parents[2] / "assets" / "robot.urdf",
        Path(__file__).resolve().parents[3] / "assets" / "robot.urdf",
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return Response(content=candidate.read_text(encoding="utf-8"), media_type="application/xml")

    # Recursive fallback search across root parent directories
    search_root = ROOT if ROOT.exists() else Path.cwd()
    if search_root.parent.exists():
        search_root = search_root.parent
    try:
        for p in search_root.rglob("robot.urdf"):
            if p.is_file():
                return Response(content=p.read_text(encoding="utf-8"), media_type="application/xml")
    except Exception:  # noqa: BLE001
        pass

    raise HTTPException(404, "URDF file 'robot.urdf' not found on system")


@router.get("/api/help")
async def help_bundle():
    from ..help_schema import PAGE_GUIDE, PARAMETER_HELP, SETUP_STEPS

    return {
        "parameters": PARAMETER_HELP,
        "pages": PAGE_GUIDE,
        "setup_steps": SETUP_STEPS,
    }


@router.get("/api/motors")
async def list_motors(request: Request):
    cfg = request.app.state.duck
    return [
        {"name": name, **joint.model_dump()}
        for name, joint in cfg.joints.items()
    ]


@router.get("/api/system")
async def system_snapshot(request: Request):
    snap = request.app.state.bus.get_snapshot()
    return snap.get("system", {})


@router.get("/api/network")
async def network_settings():
    from ..services.network import network_snapshot

    return await network_snapshot()


@router.get("/api/bluetooth/status")
async def bluetooth_status():
    from ..services.bluetooth import adapter_status

    return await adapter_status()


@router.get("/api/bluetooth/devices")
async def bluetooth_devices():
    from ..services.bluetooth import BluetoothError, list_devices

    try:
        return {"devices": await list_devices()}
    except BluetoothError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.post("/api/bluetooth/scan")
async def bluetooth_scan(request: Request):
    from ..services.bluetooth import BluetoothError, scan

    body = {}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    duration = float(body.get("duration_s", 8) if isinstance(body, dict) else 8)
    try:
        devices = await scan(duration)
        return {"ok": True, "devices": devices, "duration_s": duration}
    except BluetoothError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.post("/api/bluetooth/power")
async def bluetooth_power(request: Request):
    from ..services.bluetooth import BluetoothError, set_powered

    body = await request.json()
    on = bool(body.get("on", True))
    try:
        return await set_powered(on)
    except BluetoothError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.post("/api/bluetooth/pair")
async def bluetooth_pair(request: Request):
    from ..services.bluetooth import BluetoothError, pair_device

    body = await request.json()
    address = body.get("address")
    if not address:
        raise HTTPException(400, "address required")
    try:
        return await pair_device(str(address))
    except BluetoothError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/bluetooth/connect")
async def bluetooth_connect(request: Request):
    from ..services.bluetooth import BluetoothError, connect_device

    body = await request.json()
    address = body.get("address")
    if not address:
        raise HTTPException(400, "address required")
    try:
        return await connect_device(str(address))
    except BluetoothError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/bluetooth/disconnect")
async def bluetooth_disconnect(request: Request):
    from ..services.bluetooth import BluetoothError, disconnect_device

    body = await request.json()
    address = body.get("address")
    if not address:
        raise HTTPException(400, "address required")
    try:
        return await disconnect_device(str(address))
    except BluetoothError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/bluetooth/remove")
async def bluetooth_remove(request: Request):
    from ..services.bluetooth import BluetoothError, remove_device

    body = await request.json()
    address = body.get("address")
    if not address:
        raise HTTPException(400, "address required")
    try:
        return await remove_device(str(address))
    except BluetoothError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/api/input/keymap")
async def keymap(request: Request):
    return request.app.state.duck.control.get("keymap", {})


@router.get("/api/scripts")
async def list_scripts(request: Request):
    manifest = load_script_manifest()
    items = []
    for path in sorted(SCRIPTS_DIR.glob("*.py")):
        meta = manifest.get("scripts", {}).get(path.name, {})
        node_id = f"script.{path.stem}"
        node = request.app.state.registry.get_optional(node_id)
        items.append(
            {
                "name": path.name,
                "node_id": node_id,
                "display_name": meta.get("display_name", path.name),
                "description": meta.get("description", ""),
                "resources": meta.get("resources", []),
                "state": node.state.value if node else "created",
            }
        )
    return items


@router.get("/api/scripts/{name}")
async def read_script(name: str):
    path = _safe_script(name)
    return {"name": name, "content": path.read_text()}


@router.put("/api/scripts/{name}")
async def write_script(name: str, request: Request):
    if not request.app.state.duck.allow_script_runner:
        raise HTTPException(403, "Script runner disabled")
    body = await request.json()
    content = body.get("content", "")
    path = _safe_script(name, must_exist=False)
    path.write_text(content)
    # Ensure node exists
    node_id = f"script.{path.stem}"
    if request.app.state.registry.get_optional(node_id) is None:
        manifest = load_script_manifest()
        meta = manifest.get("scripts", {}).get(path.name, {})
        node = ScriptNode(
            bus=request.app.state.bus,
            locks=request.app.state.locks,
            script_path=path,
            display_name=meta.get("display_name"),
            resources=meta.get("resources"),
            depends_on=meta.get("depends_on"),
            description=meta.get("description", ""),
        )
        request.app.state.registry.register(node)
    return {"ok": True, "name": name}


@router.post("/api/scripts/{name}/run")
async def run_script(name: str, request: Request):
    if not request.app.state.duck.allow_script_runner:
        raise HTTPException(403, "Script runner disabled")
    path = _safe_script(name)
    node_id = f"script.{path.stem}"
    if request.app.state.registry.get_optional(node_id) is None:
        for n in discover_script_nodes(
            request.app.state.bus, request.app.state.locks, load_script_manifest()
        ):
            if n.id == node_id:
                request.app.state.registry.register(n)
                break
    return (await request.app.state.registry.start(node_id)).model_dump()


@router.post("/api/scripts/{name}/stop")
async def stop_script(name: str, request: Request):
    path = _safe_script(name)
    node_id = f"script.{path.stem}"
    return (await request.app.state.registry.stop(node_id)).model_dump()


@router.get("/api/boards")
async def list_boards(request: Request):
    boards_dir: Path = request.app.state.boards_dir
    out = []
    if boards_dir.exists():
        for p in sorted(boards_dir.glob("*.json")):
            out.append(json.loads(p.read_text()))
    return out


@router.get("/api/pinout")
async def get_pinout(request: Request):
    return request.app.state.pinout


@router.put("/api/pinout")
async def put_pinout(request: Request):
    body = await request.json()
    request.app.state.pinout = body
    save_json(request.app.state.pinout_path, body)
    return body


@router.get("/api/pinout/export")
async def export_pinout(request: Request):
    return request.app.state.pinout


@router.post("/api/pinout/import")
async def import_pinout(request: Request):
    body = await request.json()
    request.app.state.pinout = body
    save_json(request.app.state.pinout_path, body)
    return {"ok": True}


@router.websocket("/ws/telemetry")
async def ws_telemetry(ws: WebSocket):
    await ws.accept()
    bus = ws.app.state.bus
    q = bus.subscribe()
    try:
        await ws.send_json(bus.get_snapshot())
        while True:
            payload = await q.get()
            await ws.send_json(payload)
    except (WebSocketDisconnect, RuntimeError, Exception):
        pass
    finally:
        bus.unsubscribe(q)


@router.websocket("/ws/nodes/events")
async def ws_node_events(ws: WebSocket):
    await ws.accept()
    bus = ws.app.state.bus
    q = bus.subscribe_events()
    try:
        while True:
            payload = await q.get()
            await ws.send_json(payload)
    except (WebSocketDisconnect, RuntimeError, Exception):
        pass
    finally:
        bus.unsubscribe_events(q)


@router.websocket("/ws/nodes/{node_id}/logs")
async def ws_node_logs(ws: WebSocket, node_id: str):
    await ws.accept()
    bus = ws.app.state.bus
    last = 0
    try:
        while True:
            lines = bus.get_logs(node_id)
            if len(lines) > last:
                for line in lines[last:]:
                    await ws.send_json({"line": line})
                last = len(lines)
            await asyncio.sleep(0.25)
    except (WebSocketDisconnect, RuntimeError, Exception):
        pass


@router.get("/api/logs/all")
async def get_all_logs(request: Request, limit: int = 500, node_id: str | None = None):
    bus = request.app.state.bus
    return {"logs": bus.get_all_logs(limit=limit, node_id=node_id)}


@router.websocket("/ws/logs/all")
async def ws_all_logs(ws: WebSocket):
    await ws.accept()
    bus = ws.app.state.bus
    q = bus.subscribe_logs()
    try:
        # Initial snapshot of recent logs
        for entry in bus.get_all_logs(limit=200):
            await ws.send_json(entry)
        while True:
            entry = await q.get()
            await ws.send_json(entry)
    except (WebSocketDisconnect, RuntimeError, Exception):
        pass
    finally:
        bus.unsubscribe_logs(q)


@router.get("/stream/camera")
async def stream_camera(request: Request):
    video = request.app.state.registry.get_optional("video.capture")
    if video is None or video.state.value != "running":
        raise HTTPException(503, "video.capture node is not running")

    async def gen():
        boundary = b"frame"
        while True:
            if video.state.value != "running":
                break
            jpeg = await video.get_jpeg()
            if jpeg:
                yield (
                    b"--" + boundary + b"\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
                )
            await asyncio.sleep(1 / 15)

    return StreamingResponse(
        gen(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


def _safe_script(name: str, must_exist: bool = True) -> Path:
    if "/" in name or "\\" in name or ".." in name or not name.endswith(".py"):
        raise HTTPException(400, "Invalid script name")
    path = (SCRIPTS_DIR / name).resolve()
    if SCRIPTS_DIR.resolve() not in path.parents and path != SCRIPTS_DIR.resolve():
        # ensure under scripts dir
        if path.parent != SCRIPTS_DIR.resolve():
            raise HTTPException(400, "Path escape blocked")
    if must_exist and not path.exists():
        raise HTTPException(404, f"Script not found: {name}")
    return path
