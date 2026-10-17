"""Companion (Duck Brain) API: head gestures, eyes, ears, lamp, speech and e-stop.

These routes are also MCP tools (see mcp_server.py, _COMPANION_OPS), so their
docstrings and field descriptions are what an AI agent reads. Everything is
clamped server-side by the nodes, whoever the caller is.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..nodes.audio_io import AudioIONode
from ..nodes.eyes_link import EyesLinkNode, EyesUnavailable
from ..nodes.head_control import HeadControlNode
from ..schemas import NodeState

router = APIRouter(tags=["companion"])

BRAIN_STALE_S = 10.0


class LookAtReq(BaseModel):
    yaw: float = Field(description="Degrees; positive turns the head to the duck's left. Safe range about -60..60.")
    pitch: float = Field(description="Degrees; head pitch. Safe range about -60..45.")
    roll: Optional[float] = Field(default=None, description="Optional head roll in degrees, about -20..20.")


class TimesReq(BaseModel):
    times: int = Field(default=1, description="How many repetitions (capped at 3).")


class TiltReq(BaseModel):
    angle: float = Field(description="Head roll in degrees, about -20..20 (curious head tilt).")


class IdleMotionReq(BaseModel):
    enabled: bool = Field(description="Breathing/sway idle motion on or off.")
    breath_deg: Optional[float] = Field(default=None, description="Breath amplitude in degrees (0-4).")
    sway_deg: Optional[float] = Field(default=None, description="Sway amplitude in degrees (0-4).")


class ExpressionReq(BaseModel):
    name: str = Field(description="Expression name, see eyes_list_expressions (e.g. happy, sad, thinking).")
    hold_s: Optional[float] = Field(default=None, ge=0, le=60,
                                    description="Return to neutral after this many seconds; omit to keep it.")


class EyesLookReq(BaseModel):
    x: float = Field(ge=-1, le=1, description="Gaze left/right, -1..1 (from the viewer's side).")
    y: float = Field(ge=-1, le=1, description="Gaze up/down, -1 (up)..1 (down).")
    hold_s: Optional[float] = Field(default=None, ge=0, le=30)


class IdleReq(BaseModel):
    enabled: bool


class EarsReq(BaseModel):
    left: Optional[float] = Field(default=None, description="Left ear, -1 (back/down) .. 1 (forward/up); 0 is neutral. Omit to keep it.")
    right: Optional[float] = Field(default=None, description="Right ear, -1 .. 1; 0 is neutral. Omit to keep it.")


class EarGestureReq(BaseModel):
    name: str = Field(description="wiggle, perk, droop, flick_left, flick_right or alert.")
    times: int = Field(default=1, description="Repetitions for wiggle/alert (capped at 3).")


class EarsEnableReq(BaseModel):
    enabled: bool = Field(description="On: the ears can be driven. Off: never driven (silent).")
    side: Optional[str] = Field(default=None, description="left or right; omit for both.")


class LampReq(BaseModel):
    on: Optional[bool] = Field(default=None, description="Switch the head lamp on or off.")
    brightness: Optional[float] = Field(default=None, ge=0, le=1, description="0..1; dims the lamp.")


class LampBlinkReq(BaseModel):
    times: int = Field(default=2, ge=1, le=5, description="Number of flashes (1-5).")


class SayReq(BaseModel):
    text: str = Field(max_length=400, description="Sentence for the duck to say out loud.")


class VoiceReq(BaseModel):
    pitch: Optional[float] = Field(default=None, description="0.5..2; above 1 is higher and cuter.")
    speed: Optional[float] = Field(default=None, description="0.5..2; above 1 talks faster.")


class HeartbeatReq(BaseModel):
    name: str = "brain"
    detail: str = ""


# ------------------------------------------------------------------ helpers


def _node(request: Request, node_id: str, cls: type) -> Any:
    node = request.app.state.registry.get_optional(node_id)
    if not isinstance(node, cls):
        raise HTTPException(503, f"{node_id} is not available")
    if node.state != NodeState.RUNNING:
        raise HTTPException(503, f"{node_id} is not running; start it on System -> Nodes")
    return node


def _head(request: Request) -> HeadControlNode:
    return _node(request, "head.control", HeadControlNode)


def _eyes(request: Request) -> EyesLinkNode:
    return _node(request, "eyes.link", EyesLinkNode)


def _audio(request: Request) -> AudioIONode:
    return _node(request, "audio.io", AudioIONode)


async def _eyes_call(request: Request, method: str, path: str, json: Any = None) -> Any:
    try:
        return await _eyes(request).request(method, path, json)
    except EyesUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


# ------------------------------------------------------------------ head


@router.post("/api/head/look_at", operation_id="head_look_at")
async def head_look_at(req: LookAtReq, request: Request):
    """Turn the duck's head to yaw/pitch (and optional roll) in degrees. Values outside the safe range are clamped; the response says what was applied."""
    return _head(request).look_at(req.yaw, req.pitch, req.roll)


@router.post("/api/head/nod", operation_id="head_nod")
async def head_nod(req: TimesReq, request: Request):
    """Nod the head (yes). times is capped at 3."""
    return _head(request).nod(req.times)


@router.post("/api/head/shake", operation_id="head_shake")
async def head_shake(req: TimesReq, request: Request):
    """Shake the head (no). times is capped at 3."""
    return _head(request).shake(req.times)


@router.post("/api/head/tilt", operation_id="head_tilt")
async def head_tilt(req: TiltReq, request: Request):
    """Tilt the head sideways (roll) by angle degrees, e.g. a curious tilt."""
    return _head(request).tilt(req.angle)


@router.post("/api/head/center", operation_id="head_center")
async def head_center(request: Request):
    """Return the head to the neutral, centred pose."""
    return _head(request).center()


@router.post("/api/head/stop", operation_id="head_stop")
async def head_stop(request: Request):
    """Stop all head motion immediately and hold the current position."""
    return _head(request).halt()


@router.get("/api/head/state", operation_id="head_state")
async def head_state(request: Request):
    """Current head joint angles, targets, limits and recent safety events."""
    return _head(request).snapshot()


@router.post("/api/head/idle_motion", operation_id="head_idle_motion")
async def head_idle_motion(req: IdleMotionReq, request: Request):
    """Turn the gentle breathing/sway idle motion on or off. It's layered on every pose and stays within limits."""
    return _head(request).set_idle_motion(req.enabled, req.breath_deg, req.sway_deg)


# ------------------------------------------------------------------ eyes


@router.get("/api/eyes/expressions", operation_id="eyes_list_expressions")
async def eyes_list_expressions(request: Request):
    """List the eye expressions the duck can show."""
    return await _eyes_call(request, "GET", "/expressions")


@router.post("/api/eyes/expression", operation_id="eyes_set_expression")
async def eyes_set_expression(req: ExpressionReq, request: Request):
    """Show an eye expression (happy, sad, angry, surprised, sleepy, thinking, listening, curious, suspicious, grumpy, neutral)."""
    return await _eyes_call(request, "POST", "/expression", req.model_dump(exclude_none=True))


@router.post("/api/eyes/look", operation_id="eyes_look")
async def eyes_look(req: EyesLookReq, request: Request):
    """Move the eyes' gaze without moving the head. x and y are -1..1."""
    return await _eyes_call(request, "POST", "/look", req.model_dump(exclude_none=True))


@router.post("/api/eyes/blink", operation_id="eyes_blink")
async def eyes_blink(request: Request):
    """Blink once."""
    return await _eyes_call(request, "POST", "/blink")


@router.post("/api/eyes/idle", operation_id="eyes_idle")
async def eyes_idle(req: IdleReq, request: Request):
    """Enable or disable idle eye wandering when no gaze is commanded."""
    return await _eyes_call(request, "POST", "/idle", req.model_dump())


@router.get("/api/eyes/state", operation_id="eyes_state")
async def eyes_state(request: Request):
    """Current expression and gaze of the eyes."""
    return await _eyes_call(request, "GET", "/state")


@router.get("/api/eyes/preview")
async def eyes_preview(request: Request):
    png = await _eyes_call(request, "GET", "/preview.png")
    return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.get("/api/eyes/calibration")
async def eyes_get_calibration(request: Request):
    return await _eyes_call(request, "GET", "/calibration")


@router.put("/api/eyes/calibration")
async def eyes_put_calibration(request: Request):
    return await _eyes_call(request, "PUT", "/calibration", await request.json())


# ------------------------------------------------------------------ ears & lamp (head Pi Zero)


@router.post("/api/ears/set", operation_id="ears_set")
async def ears_set(req: EarsReq, request: Request):
    """Move the ear servos. Each ear is -1..1 (0 neutral, positive = up/forward); out-of-range values are clamped and reported."""
    return await _eyes_call(request, "POST", "/ears", req.model_dump(exclude_none=True))


@router.post("/api/ears/gesture", operation_id="ears_gesture")
async def ears_gesture(req: EarGestureReq, request: Request):
    """Ear gesture: wiggle (playful), perk (interested), droop (sad/tired), flick_left/flick_right, alert (surprised)."""
    return await _eyes_call(request, "POST", "/ears/gesture", req.model_dump())


@router.post("/api/ears/idle", operation_id="ears_idle")
async def ears_idle(req: IdleReq, request: Request):
    """Turn occasional idle ear twitches on or off."""
    return await _eyes_call(request, "POST", "/ears/idle", req.model_dump())


@router.post("/api/ears/release", operation_id="ears_release")
async def ears_release(request: Request):
    """Stop driving the ear servos (they go limp)."""
    return await _eyes_call(request, "POST", "/ears/release")


# Operator switch for the hardware; deliberately not an MCP tool, so an AI agent
# can't switch ears back on that a person turned off.
@router.post("/api/ears/enable")
async def ears_enable(req: EarsEnableReq, request: Request):
    """Switch the ear servos on or off (saved on the head Zero)."""
    return await _eyes_call(request, "POST", "/ears/enable", req.model_dump(exclude_none=True))


@router.get("/api/ears/state", operation_id="ears_state")
async def ears_state(request: Request):
    """Ear positions, targets, limit, driver and available gestures."""
    return await _eyes_call(request, "GET", "/ears")


@router.post("/api/lamp/set", operation_id="lamp_set")
async def lamp_set(req: LampReq, request: Request):
    """Switch the head lamp on/off or set its brightness (0..1)."""
    return await _eyes_call(request, "POST", "/lamp", req.model_dump(exclude_none=True))


@router.post("/api/lamp/blink", operation_id="lamp_blink")
async def lamp_blink(req: LampBlinkReq, request: Request):
    """Flash the head lamp a few times."""
    return await _eyes_call(request, "POST", "/lamp/blink", req.model_dump())


@router.get("/api/lamp/state", operation_id="lamp_state")
async def lamp_state(request: Request):
    """Whether the head lamp is on, and its brightness."""
    return await _eyes_call(request, "GET", "/lamp")


# ------------------------------------------------------------------ speech


@router.post("/api/speech/say", operation_id="speech_say")
async def speech_say(req: SayReq, request: Request):
    """Say a short sentence out loud through the duck's speaker."""
    return await _audio(request).say(req.text)


@router.post("/api/speech/stop", operation_id="speech_stop")
async def speech_stop(request: Request):
    """Stop talking and drop anything queued."""
    await _audio(request).stop_speaking()
    return {"ok": True}


@router.post("/api/speech/voice")
async def speech_voice(req: VoiceReq, request: Request):
    """Tune the voice live (not saved; set companion.audio.voice_pitch/voice_speed to keep it)."""
    return _audio(request).set_voice(req.pitch, req.speed)


@router.websocket("/ws/audio")
async def ws_audio(ws: WebSocket):
    """speech_start / utterance (base64 WAV) / speech_end / speaking events for the brain."""
    await ws.accept()
    node = ws.app.state.registry.get_optional("audio.io")
    if not isinstance(node, AudioIONode) or node.state != NodeState.RUNNING:
        await ws.send_json({"type": "error", "detail": "audio.io is not running"})
        await ws.close()
        return
    q = node.subscribe()
    await ws.send_json({"type": "hello", **node.status()})
    try:
        while True:
            await ws.send_json(await q.get())
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        node.unsubscribe(q)


# ------------------------------------------------------------------ safety & status


@router.post("/api/estop", operation_id="estop")
async def estop(request: Request):
    """Emergency stop: freeze the head and ears, set the eyes to neutral and stop talking. Always allowed."""
    registry = request.app.state.registry
    done: dict[str, Any] = {}
    head = registry.get_optional("head.control")
    if isinstance(head, HeadControlNode) and head.state == NodeState.RUNNING:
        done["head"] = head.halt()
    audio = registry.get_optional("audio.io")
    if isinstance(audio, AudioIONode) and audio.state == NodeState.RUNNING:
        await audio.stop_speaking()
        done["speech"] = "stopped"
    eyes = registry.get_optional("eyes.link")
    if isinstance(eyes, EyesLinkNode) and eyes.state == NodeState.RUNNING:
        try:
            await eyes.request("POST", "/expression", {"name": "neutral"})
            done["eyes"] = "neutral"
        except (EyesUnavailable, ValueError) as exc:
            done["eyes"] = f"unavailable: {exc}"
        try:
            # Ears hold where they are (no neutral jump, which would be a movement).
            await eyes.request("POST", "/ears/stop")
            done["ears"] = "stopped"
        except (EyesUnavailable, ValueError) as exc:
            done["ears"] = f"unavailable: {exc}"
    for node in (head, audio, eyes):
        if node is not None:
            node.log("ESTOP")
    return {"ok": True, **done}


@router.post("/api/companion/heartbeat")
async def companion_heartbeat(req: HeartbeatReq, request: Request):
    request.app.state.brain_seen = {"ts": time.time(), "name": req.name, "detail": req.detail}
    return {"ok": True}


@router.get("/api/companion/status", operation_id="companion_status")
async def companion_status(request: Request):
    """Robot readiness: head servos, eyes, ears, lamp, mic/speaker, camera stream and brain heartbeat."""
    registry = request.app.state.registry
    out: dict[str, Any] = {"ts": time.time()}

    head = registry.get_optional("head.control")
    if isinstance(head, HeadControlNode) and head.state == NodeState.RUNNING:
        st = head.snapshot()
        found = sum(1 for v in st["present_deg"].values() if v is not None)
        # Mock mode reports simulated positions; never call that healthy.
        found = 0 if st["mock"] else found
        out["servos"] = {"ok": found == 4, "found": found, "expected": 4, "mock": st["mock"]}
    else:
        out["servos"] = {"ok": False, "found": 0, "expected": 4, "detail": "head.control not running"}

    eyes = registry.get_optional("eyes.link")
    out["eyes"] = {"online": bool(isinstance(eyes, EyesLinkNode) and eyes.online),
                   "url": getattr(eyes, "url", None)}
    ears = getattr(eyes, "ears_state", {}) if out["eyes"]["online"] else {}
    out["ears"] = {"ok": bool(ears) and ears.get("driver") != "mock", "driver": ears.get("driver"),
                   "active": ears.get("active", False), "errors": ears.get("errors", []),
                   "enabled": ears.get("enabled", {})}
    lamp = getattr(eyes, "lamp_state", {}) if out["eyes"]["online"] else {}
    out["lamp"] = {"ok": bool(lamp) and lamp.get("driver") != "mock", "on": lamp.get("on", False),
                   "brightness": lamp.get("brightness", 0.0), "error": lamp.get("error")}

    audio = registry.get_optional("audio.io")
    if isinstance(audio, AudioIONode) and audio.state == NodeState.RUNNING:
        out["audio"] = audio.status()
    else:
        out["audio"] = {"mic": False, "speaker": False}

    stream_id = request.app.state.duck.companion.camera_stream
    hub = request.app.state.frames
    stream = hub.get(stream_id)
    out["camera"] = {"stream": stream_id, "live": bool(stream is not None and hub.is_live(stream))}

    seen = getattr(request.app.state, "brain_seen", None)
    if seen and time.time() - seen["ts"] < BRAIN_STALE_S:
        out["brain"] = {"online": True, "detail": seen.get("detail") or seen.get("name")}
    else:
        out["brain"] = {"online": False, "detail": "waiting"}
    return out

