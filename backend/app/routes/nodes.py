from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..runtime.locks import ResourceBusyError

router = APIRouter(prefix="/api/nodes", tags=["nodes"])


@router.get("")
async def list_nodes(request: Request):
    return [n.model_dump() for n in request.app.state.registry.list()]


@router.get("/{node_id}")
async def get_node(node_id: str, request: Request):
    try:
        return request.app.state.registry.get(node_id).info().model_dump()
    except KeyError as exc:
        raise HTTPException(404, f"Unknown node {node_id}") from exc


@router.post("/{node_id}/start")
async def start_node(node_id: str, request: Request):
    try:
        return (await request.app.state.registry.start(node_id)).model_dump()
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ResourceBusyError as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, str(exc)) from exc


@router.post("/{node_id}/stop")
async def stop_node(node_id: str, request: Request):
    try:
        return (await request.app.state.registry.stop(node_id)).model_dump()
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/{node_id}/kill")
async def kill_node(node_id: str, request: Request):
    try:
        return (await request.app.state.registry.kill(node_id)).model_dump()
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/{node_id}/restart")
async def restart_node(node_id: str, request: Request):
    try:
        return (await request.app.state.registry.restart(node_id)).model_dump()
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ResourceBusyError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/{node_id}/config")
async def get_config(node_id: str, request: Request):
    try:
        return request.app.state.registry.get(node_id).get_config()
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.put("/{node_id}/config")
async def put_config(node_id: str, request: Request):
    body = await request.json()
    try:
        node = request.app.state.registry.get(node_id)
        await node.set_config(body if isinstance(body, dict) else {})
        return node.get_config()
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/{node_id}/logs")
async def get_logs(node_id: str, request: Request):
    return {"lines": request.app.state.bus.get_logs(node_id)}
