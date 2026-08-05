from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Callable, Optional

from fastapi import APIRouter, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from ..config_loader import ASSETS_DIR, SCRIPTS_DIR, save_json
from ..nodes.script_node import make_script_node
from ..runtime.locks import ResourceBusyError
from ..services import script_fs
from ..services.script_templates import list_templates as list_script_templates
from ..services.script_templates import render as render_script_template
from ..services.script_templates import template_resources
from .video import stream_video

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
        "note": "Configuration saved successfully.",
    }


@router.get("/api/robot/urdf")
async def get_robot_urdf():
    urdf = ASSETS_DIR / "robot.urdf"
    if not urdf.is_file():
        raise HTTPException(
            404,
            f"robot.urdf not found in {ASSETS_DIR}. Copy the robot description from "
            "Open_Duck_Mini/mini_bdx/robots/open_duck_mini_v2/.",
        )
    return Response(content=urdf.read_text(encoding="utf-8"), media_type="application/xml")


@router.get("/api/robot/assets/{filename}")
async def get_robot_asset(filename: str):
    """Serve a mesh referenced by the URDF.

    Deliberately limited to assets/: the meshes under Open_Duck_Mini/print/ share
    the same names but are modelled in millimetres, and serving those makes the
    viewer render a 1000x oversized, disassembled robot.
    """
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(400, "Invalid filename")

    path = ASSETS_DIR / filename
    if not path.is_file():
        # Meshes are referenced with the case used by the CAD export; be forgiving.
        match = next(
            (p for p in ASSETS_DIR.glob("*") if p.is_file() and p.name.lower() == filename.lower()),
            None,
        )
        if match is None:
            raise HTTPException(404, f"Asset '{filename}' not found in {ASSETS_DIR}")
        path = match

    return FileResponse(path, media_type="model/stl" if path.suffix.lower() == ".stl" else None)


@router.get("/api/robot/model")
async def get_robot_model(request: Request):
    """Kinematic summary of the URDF for the 3D viewer.

    The viewer needs joint limits, axes and the link tree to build MuJoCo-style
    controls; parsing that here keeps the XML handling in one place.
    """
    import xml.etree.ElementTree as ET

    urdf = ASSETS_DIR / "robot.urdf"
    if not urdf.is_file():
        raise HTTPException(404, f"robot.urdf not found in {ASSETS_DIR}")

    try:
        root = ET.fromstring(urdf.read_text(encoding="utf-8"))
    except ET.ParseError as exc:
        raise HTTPException(500, f"robot.urdf is not valid XML: {exc}") from exc

    def _floats(text: str | None, count: int) -> list[float]:
        parts = (text or "").split()
        out = [float(p) for p in parts[:count]]
        return out + [0.0] * (count - len(out))

    joints = []
    children: set[str] = set()
    for j in root.findall("joint"):
        parent_el = j.find("parent")
        child_el = j.find("child")
        limit_el = j.find("limit")
        axis_el = j.find("axis")
        origin_el = j.find("origin")
        child = child_el.get("link") if child_el is not None else None
        if child:
            children.add(child)
        entry = {
            "name": j.get("name"),
            "type": j.get("type"),
            "parent": parent_el.get("link") if parent_el is not None else None,
            "child": child,
            "axis": _floats(axis_el.get("xyz") if axis_el is not None else None, 3),
            "origin_xyz": _floats(origin_el.get("xyz") if origin_el is not None else None, 3),
            "origin_rpy": _floats(origin_el.get("rpy") if origin_el is not None else None, 3),
        }
        if limit_el is not None:
            entry["limit"] = {
                "lower": float(limit_el.get("lower") or 0.0),
                "upper": float(limit_el.get("upper") or 0.0),
                "effort": float(limit_el.get("effort") or 0.0),
                "velocity": float(limit_el.get("velocity") or 0.0),
            }
        joints.append(entry)

    links = [l.get("name") for l in root.findall("link")]
    roots = [name for name in links if name not in children]
    meshes = sorted({(m.get("filename") or "").split("/")[-1] for m in root.iter("mesh")})
    missing = [m for m in meshes if m and not (ASSETS_DIR / m).is_file()]

    cfg = request.app.state.duck
    movable = [j for j in joints if j["type"] in ("revolute", "continuous", "prismatic")]

    return {
        "robot_name": root.get("name"),
        "urdf": "/api/robot/urdf",
        "asset_base": "/api/robot/assets",
        "up_axis": "z",
        "links": links,
        "root_link": roots[0] if roots else None,
        "joints": joints,
        "movable_joints": [j["name"] for j in movable],
        # Joints the servo bus actually reports, so the UI can show which of the
        # URDF joints are driven by live telemetry versus posed by hand.
        "actuated_joints": [name for name in cfg.joints if name in {j["name"] for j in movable}],
        "mesh_count": len(meshes),
        "missing_meshes": missing,
    }


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


def _script_state_lookup(request: Request) -> Callable[[str], Optional[str]]:
    registry = request.app.state.registry

    def state_of(node_id: str) -> Optional[str]:
        node = registry.get_optional(node_id)
        return node.state.value if node else None

    return state_of


def _require_script_runner(request: Request) -> None:
    if not request.app.state.duck.allow_script_runner:
        raise HTTPException(403, "Script runner is disabled (allow_script_runner=false)")


def _ensure_script_node(request: Request, rel: str) -> str:
    """Register a node for this script if it has none yet, and return its id."""
    path = script_fs.resolve(rel)
    if not path.is_file() or path.suffix != ".py":
        raise HTTPException(400, f"Not a Python script: {rel}")
    normalized = script_fs.relative(path)
    node_id = script_fs.node_id_for(normalized)
    if request.app.state.registry.get_optional(node_id) is None:
        request.app.state.registry.register(
            make_script_node(
                request.app.state.bus, request.app.state.locks, normalized, path
            )
        )
    return node_id


@router.get("/api/scripts")
async def list_scripts(request: Request):
    """Flat list of every Python file under robot_scripts/, at any depth."""
    state_of = _script_state_lookup(request)
    manifest = script_fs.manifest_scripts()
    items = []
    for rel in script_fs.list_python_files():
        meta = script_fs.manifest_meta(rel, manifest)
        node_id = script_fs.node_id_for(rel)
        items.append(
            {
                "name": rel,
                "node_id": node_id,
                "display_name": meta.get("display_name") or Path(rel).name,
                "description": meta.get("description")
                or script_fs.docstring_summary(SCRIPTS_DIR / rel),
                "resources": meta.get("resources", []),
                "state": state_of(node_id) or "created",
            }
        )
    return items


@router.get("/api/scripts/tree")
async def scripts_tree(request: Request):
    return {
        "root": SCRIPTS_DIR.name,
        "writable": bool(request.app.state.duck.allow_script_runner),
        "tree": script_fs.build_tree(_script_state_lookup(request)),
    }


@router.get("/api/scripts/templates")
async def scripts_templates():
    return list_script_templates()


@router.get("/api/scripts/file/{rel:path}")
async def read_script(rel: str):
    return script_fs.read_file(rel)


@router.put("/api/scripts/file/{rel:path}")
async def write_script(rel: str, request: Request):
    _require_script_runner(request)
    body = await request.json()
    path = script_fs.write_file(rel, str(body.get("content", "")))
    return {"ok": True, "path": script_fs.relative(path)}


@router.post("/api/scripts/file")
async def create_script(request: Request):
    _require_script_runner(request)
    body = await request.json()
    folder = str(body.get("folder") or "").strip().strip("/")
    name = str(body.get("name") or "").strip()
    if name and "." not in name:
        name = f"{name}.py"
    script_fs.validate_name(name)
    rel = f"{folder}/{name}" if folder else name

    template = str(body.get("template") or "blank")
    display_name = str(body.get("display_name") or "").strip()
    description = str(body.get("description") or "").strip()
    try:
        content = render_script_template(template, name, description, display_name)
    except KeyError as exc:
        raise HTTPException(400, f"Unknown template '{template}'") from exc
    if "resources" in body:
        resources = [str(r) for r in (body.get("resources") or []) if str(r).strip()]
    else:
        resources = template_resources(template)

    path = script_fs.create_file(rel, content)
    normalized = script_fs.relative(path)
    if path.suffix == ".py":
        script_fs.set_manifest_entry(
            normalized,
            {
                "display_name": display_name or path.stem.replace("_", " ").title(),
                "description": description or f"Created from the {template} template.",
                "resources": resources,
            },
        )
        _ensure_script_node(request, normalized)
    return {"ok": True, "path": normalized}


@router.post("/api/scripts/folder")
async def create_script_folder(request: Request):
    _require_script_runner(request)
    body = await request.json()
    folder = str(body.get("folder") or "").strip().strip("/")
    name = script_fs.validate_name(str(body.get("name") or ""))
    path = script_fs.create_folder(f"{folder}/{name}" if folder else name)
    return {"ok": True, "path": script_fs.relative(path)}


@router.post("/api/scripts/rename")
async def rename_script(request: Request):
    _require_script_runner(request)
    body = await request.json()
    src = str(body.get("from") or "")
    dst = str(body.get("to") or "")
    stale = script_fs.python_files_under(script_fs.resolve(src))
    _, dst_path = script_fs.rename(src, dst)
    for rel in stale:
        await request.app.state.registry.unregister(script_fs.node_id_for(rel))
    for rel in script_fs.python_files_under(dst_path):
        if script_fs.manifest_meta(rel):
            _ensure_script_node(request, rel)
    return {"ok": True, "path": script_fs.relative(dst_path)}


@router.delete("/api/scripts/file/{rel:path}")
async def delete_script(rel: str, request: Request):
    _require_script_runner(request)
    path = script_fs.resolve(rel)
    normalized = script_fs.relative(path)
    affected = script_fs.python_files_under(path)
    script_fs.delete(rel)
    for item in affected:
        await request.app.state.registry.unregister(script_fs.node_id_for(item))
    script_fs.drop_manifest_entries(affected or [normalized])
    return {"ok": True, "path": normalized}


@router.post("/api/scripts/run/{rel:path}")
async def run_script(rel: str, request: Request):
    _require_script_runner(request)
    node_id = _ensure_script_node(request, rel)
    try:
        return (await request.app.state.registry.start(node_id)).model_dump()
    except ResourceBusyError as exc:
        raise HTTPException(409, str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, str(exc)) from exc


@router.post("/api/scripts/stop/{rel:path}")
async def stop_script(rel: str, request: Request):
    node_id = script_fs.node_id_for(script_fs.relative(script_fs.resolve(rel)))
    if request.app.state.registry.get_optional(node_id) is None:
        raise HTTPException(404, f"{rel} is not running")
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
    """Alias kept for existing clients; same as /stream/video/video.capture."""
    return await stream_video("video.capture", request)


