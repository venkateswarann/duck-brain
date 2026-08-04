"""GPIO routes — REST + WebSocket endpoints for live pin control."""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["gpio"])


def _gpio(request: Request):
    """Get the GpioService from the gpio.pins node, or 404."""
    node = request.app.state.registry.get_optional("gpio.pins")
    if node is None or node.gpio is None:
        raise HTTPException(503, "gpio.pins node is not running — start it from System / Nodes")
    return node.gpio


# ── State ──────────────────────────────────────────────────────────

@router.get("/api/gpio/state")
async def gpio_state(request: Request):
    gpio = _gpio(request)
    return {
        "mock": gpio.is_mock,
        "pins": gpio.get_state(),
    }


# ── Setup ──────────────────────────────────────────────────────────

@router.post("/api/gpio/setup")
async def gpio_setup(request: Request):
    gpio = _gpio(request)
    body = await request.json()
    bcm = int(body["bcm"])
    direction = body.get("direction", "OUT").upper()
    pull = body.get("pull", "NONE").upper()

    from ..services.gpio import Direction, Pull as GPull

    d = Direction.IN if direction == "IN" else Direction.OUT
    p = GPull.UP if pull == "UP" else GPull.DOWN if pull == "DOWN" else GPull.NONE

    state = gpio.setup_pin(
        bcm, d, pull=p,
        device_id=body.get("device_id"),
        label=body.get("label"),
    )
    return {"ok": True, "bcm": bcm, "direction": state.direction.value}


# ── Write ──────────────────────────────────────────────────────────

@router.post("/api/gpio/write")
async def gpio_write(request: Request):
    gpio = _gpio(request)
    body = await request.json()
    bcm = int(body["bcm"])
    value = int(body.get("value", 0))
    try:
        actual = gpio.write_pin(bcm, value)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "bcm": bcm, "value": actual}


# ── Read ───────────────────────────────────────────────────────────

@router.get("/api/gpio/read/{bcm}")
async def gpio_read(request: Request, bcm: int):
    gpio = _gpio(request)
    try:
        value = gpio.read_pin(bcm)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"bcm": bcm, "value": value}


# ── PWM ────────────────────────────────────────────────────────────

@router.post("/api/gpio/pwm")
async def gpio_pwm(request: Request):
    gpio = _gpio(request)
    body = await request.json()
    bcm = int(body["bcm"])
    freq = float(body.get("frequency", 1000))
    duty = float(body.get("duty_cycle", 50))
    try:
        gpio.set_pwm(bcm, freq, duty)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "bcm": bcm, "frequency": freq, "duty_cycle": duty}


@router.post("/api/gpio/pwm/stop")
async def gpio_pwm_stop(request: Request):
    gpio = _gpio(request)
    body = await request.json()
    bcm = int(body["bcm"])
    gpio.stop_pwm(bcm)
    return {"ok": True, "bcm": bcm}


# ── Probe ──────────────────────────────────────────────────────────

@router.post("/api/gpio/probe/start")
async def gpio_probe_start(request: Request):
    gpio = _gpio(request)
    body = await request.json()
    bcm = int(body["bcm"])
    rate_hz = float(body.get("rate_hz", 50))
    try:
        await gpio.start_probe(bcm, rate_hz)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "bcm": bcm, "rate_hz": rate_hz}


@router.post("/api/gpio/probe/stop")
async def gpio_probe_stop(request: Request):
    gpio = _gpio(request)
    body = await request.json()
    bcm = int(body["bcm"])
    await gpio.stop_probe(bcm)
    return {"ok": True, "bcm": bcm}


# ── Cleanup single pin ────────────────────────────────────────────

@router.post("/api/gpio/cleanup/{bcm}")
async def gpio_cleanup(request: Request, bcm: int):
    gpio = _gpio(request)
    gpio.cleanup_pin(bcm)
    return {"ok": True, "bcm": bcm}


# ── WebSocket — live probe stream ─────────────────────────────────

@router.websocket("/ws/gpio/probe")
async def ws_gpio_probe(ws: WebSocket):
    """Stream GPIO probe samples in real time.

    Subscribes to the event bus and forwards only ``gpio_probe`` events.
    """
    await ws.accept()
    bus = ws.app.state.bus
    q = bus.subscribe_events()
    try:
        while True:
            event = await q.get()
            if event.get("type") == "gpio_probe":
                await ws.send_json({
                    "bcm": event["bcm"],
                    "value": event["value"],
                    "ts": event["ts"],
                })
    except (WebSocketDisconnect, RuntimeError, Exception):
        pass
    finally:
        bus.unsubscribe_events(q)
