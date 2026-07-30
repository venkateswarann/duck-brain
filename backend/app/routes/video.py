"""Video sources: the built-in camera node plus anything scripts publish."""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from ..services.frame_hub import MAX_FRAME_BYTES, FrameHub

router = APIRouter(tags=["video"])

CAMERA_NODE_ID = "video.capture"
BOUNDARY = b"frame"


def _hub(request: Request) -> FrameHub:
    return request.app.state.frames


def _camera_node(request: Request) -> Any:
    return request.app.state.registry.get_optional(CAMERA_NODE_ID)


def _camera_info(request: Request) -> dict[str, Any]:
    node = _camera_node(request)
    config = node.get_config() if node else {}
    return {
        "id": CAMERA_NODE_ID,
        "label": "Built-in camera (video.capture)",
        "kind": "node",
        "live": bool(node and node.state.value == "running"),
        "frames": 0,
        "fps": config.get("fps", 0),
        "width": config.get("width", 0),
        "height": config.get("height", 0),
        "publisher": CAMERA_NODE_ID,
        "mock": bool(config.get("mock")),
        "last_frame_age": 0.0,
    }


@router.get("/api/video/streams")
async def list_streams(request: Request):
    return [_camera_info(request), *_hub(request).streams()]


@router.post("/api/video/ingest/{stream_id}")
async def ingest_frame(stream_id: str, request: Request):
    """One JPEG frame from a script (see robot_scripts/dcs_sdk.py)."""
    stream_id = stream_id.strip()
    if not stream_id or stream_id == CAMERA_NODE_ID:
        raise HTTPException(400, "Invalid stream id")
    jpeg = await request.body()
    if not jpeg:
        raise HTTPException(400, "Empty frame")
    if len(jpeg) > MAX_FRAME_BYTES:
        raise HTTPException(413, "Frame too large")
    if not jpeg.startswith(b"\xff\xd8"):
        raise HTTPException(415, "Expected a JPEG frame")
    stream = _hub(request).publish(
        stream_id,
        jpeg,
        label=request.query_params.get("label", ""),
        publisher=request.query_params.get("publisher", ""),
        width=_int_param(request, "width"),
        height=_int_param(request, "height"),
    )
    return {"ok": True, "stream": stream.id, "seq": stream.seq}


@router.delete("/api/video/ingest/{stream_id}")
async def drop_stream(stream_id: str, request: Request):
    _hub(request).drop(stream_id)
    return {"ok": True}


@router.get("/api/video/snapshot/{stream_id}")
async def snapshot(stream_id: str, request: Request):
    jpeg = await _single_frame(request, stream_id)
    if jpeg is None:
        raise HTTPException(503, f"No frames available for '{stream_id}'")
    return Response(jpeg, media_type="image/jpeg")


@router.get("/stream/video/{stream_id}")
async def stream_video(stream_id: str, request: Request):
    if stream_id == CAMERA_NODE_ID:
        return _camera_stream(request)
    hub = _hub(request)
    if hub.get(stream_id) is None:
        raise HTTPException(404, f"No video stream '{stream_id}'")

    async def gen():
        seq = -1
        idle = 0.0
        while True:
            if await request.is_disconnected():
                break
            frame = await hub.next_frame(stream_id, seq, timeout=2.0)
            if frame is None:
                idle += 2.0
                # Publisher stopped: end the response so the <img> can retry.
                if idle >= 10.0 or hub.get(stream_id) is None:
                    break
                continue
            idle = 0.0
            seq, jpeg = frame
            yield _part(jpeg)

    return StreamingResponse(
        gen(), media_type=f"multipart/x-mixed-replace; boundary={BOUNDARY.decode()}"
    )


def _camera_stream(request: Request) -> StreamingResponse:
    node = _camera_node(request)
    if node is None or node.state.value != "running":
        raise HTTPException(503, "video.capture node is not running")

    async def gen():
        while True:
            if node.state.value != "running":
                break
            if await request.is_disconnected():
                break
            jpeg = await node.get_jpeg()
            if jpeg:
                yield _part(jpeg)
            fps = max(1, min(60, int(node.get_config().get("fps", 15))))
            await asyncio.sleep(1 / fps)

    return StreamingResponse(
        gen(), media_type=f"multipart/x-mixed-replace; boundary={BOUNDARY.decode()}"
    )


async def _single_frame(request: Request, stream_id: str) -> Optional[bytes]:
    if stream_id == CAMERA_NODE_ID:
        node = _camera_node(request)
        return await node.get_jpeg() if node else None
    return _hub(request).latest(stream_id)


def _part(jpeg: bytes) -> bytes:
    return (
        b"--" + BOUNDARY + b"\r\n"
        b"Content-Type: image/jpeg\r\n"
        b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n"
    )


def _int_param(request: Request, name: str) -> int:
    try:
        return int(request.query_params.get(name, "0"))
    except (TypeError, ValueError):
        return 0
