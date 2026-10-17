#!/usr/bin/env python3
"""HTTP API for the duck's eyes (runs on the head Pi Zero 2 W).

    python3 eyes_server.py                 # real GC9A01 displays
    python3 eyes_server.py --mock          # no hardware, preview only

DCS on the Pi 4 proxies these routes under /api/eyes/*, and the ear servo and
head lamp routes (/ears*, /lamp*, body_io.py) under /api/ears/* and /api/lamp/*.
"""

from __future__ import annotations

import argparse
import io
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from PIL import Image
from pydantic import BaseModel, Field

from body_io import Body
from eye_engine import EyeEngine
from eye_renderer import (
    HEIGHT,
    WIDTH,
    load_calibration,
    load_expressions,
    open_displays,
    save_calibration,
)


class ExpressionReq(BaseModel):
    name: str
    hold_s: Optional[float] = Field(default=None, ge=0, le=60)


class LookReq(BaseModel):
    x: float = Field(ge=-1.0, le=1.0)
    y: float = Field(ge=-1.0, le=1.0)
    hold_s: Optional[float] = Field(default=None, ge=0, le=30)


class ActionReq(BaseModel):
    name: str


class IdleReq(BaseModel):
    enabled: bool


class EyeCalibration(BaseModel):
    rotation: int = 0
    offset_x: int = 0
    offset_y: int = 0


class CalibrationReq(BaseModel):
    left: EyeCalibration
    right: EyeCalibration


class EarsReq(BaseModel):
    left: Optional[float] = None  # -1..1, clamped to body_config "limit"
    right: Optional[float] = None


class EarGestureReq(BaseModel):
    name: str
    times: int = 1  # capped at 3


class EarsEnableReq(BaseModel):
    enabled: bool
    side: Optional[str] = None  # "left" | "right"; omit for both


class LampReq(BaseModel):
    on: Optional[bool] = None
    brightness: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class LampBlinkReq(BaseModel):
    times: int = Field(default=2, ge=1, le=10)


def _throttled() -> str:
    """`vcgencmd get_throttled` output, so DCS can show this Pi's 5 V under-voltage."""
    import subprocess  # noqa: PLC0415

    try:
        return subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=2).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def create_app(mock: bool, fps: float) -> FastAPI:
    calibration = load_calibration()
    expressions = load_expressions()
    engine = EyeEngine(open_displays(mock, calibration), expressions, fps=fps)
    body = Body(mock)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        engine.start()
        body.start()
        yield
        try:
            body.stop()
        except Exception as exc:  # noqa: BLE001  (never skip releasing the displays)
            print(f"ears/lamp shutdown: {exc}")
        finally:
            engine.stop()

    app = FastAPI(title="Duck Eyes", lifespan=lifespan)

    @app.get("/health")
    def health():
        return {"ok": True, "mock": mock, "frames": engine.frames,
                "ears": body.ears.kind, "lamp": body.lamp.dev.kind, "throttled": _throttled()}

    @app.get("/expressions")
    def expressions_list():
        return list(expressions.keys())

    @app.get("/state")
    def state():
        return engine.state()

    @app.post("/expression")
    def set_expression(req: ExpressionReq):
        try:
            engine.set_expression(req.name, req.hold_s)
        except KeyError:
            raise HTTPException(404, f"unknown expression '{req.name}'; have {list(expressions)}")
        body.on_expression(expressions[req.name].get("ears"))
        return engine.state()

    @app.post("/look")
    def look(req: LookReq):
        engine.look(req.x, req.y, req.hold_s)
        return engine.state()

    @app.get("/actions")
    def actions_list():
        from eye_styles import ACTIONS  # noqa: PLC0415

        return list(ACTIONS)

    @app.post("/action")
    def eye_action(req: ActionReq):
        try:
            seconds = engine.action(req.name)
        except KeyError:
            from eye_styles import ACTIONS  # noqa: PLC0415

            raise HTTPException(404, f"unknown eye action '{req.name}'; have {list(ACTIONS)}")
        return {"ok": True, "action": req.name, "seconds": seconds}

    @app.post("/blink")
    def blink():
        engine.blink()
        return {"ok": True}

    @app.post("/idle")
    def idle(req: IdleReq):
        engine.set_idle(req.enabled)
        return engine.state()

    @app.get("/preview.png")
    def preview():
        images = engine.latest_images()
        if images is None:
            raise HTTPException(503, "no frame rendered yet")
        canvas = Image.new("RGB", (WIDTH * 2 + 20, HEIGHT), (0, 0, 0))
        # Left eye drawn on the viewer's right, as when facing the duck.
        canvas.paste(images[1], (0, 0))
        canvas.paste(images[0], (WIDTH + 20, 0))
        buf = io.BytesIO()
        canvas.save(buf, format="PNG")
        return Response(buf.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.get("/ears")
    def ears_state():
        return body.ears.state()

    @app.post("/ears")
    def ears_set(req: EarsReq):
        return body.ears.set(req.left, req.right)

    @app.post("/ears/gesture")
    def ears_gesture(req: EarGestureReq):
        try:
            return body.ears.gesture(req.name, req.times)
        except KeyError:
            raise HTTPException(404, f"unknown ear gesture '{req.name}'; have {list(body.ears.state()['gestures'])}")

    @app.post("/ears/idle")
    def ears_idle(req: IdleReq):
        body.ears.set_idle(req.enabled)
        return body.ears.state()

    @app.post("/ears/stop")
    def ears_stop():
        body.ears.halt()
        return body.ears.state()

    @app.post("/ears/enable")
    def ears_enable(req: EarsEnableReq):
        return body.ears.set_enabled(req.enabled, req.side)

    @app.post("/ears/release")
    def ears_release():
        body.ears.release()
        return body.ears.state()

    @app.get("/lamp")
    def lamp_state():
        return body.lamp.state()

    @app.post("/lamp")
    def lamp_set(req: LampReq):
        return body.lamp.set(req.on, req.brightness)

    @app.post("/lamp/blink")
    def lamp_blink(req: LampBlinkReq):
        return body.lamp.blink(req.times)

    @app.get("/calibration")
    def get_calibration():
        return calibration

    @app.put("/calibration")
    def put_calibration(req: CalibrationReq):
        calibration.update(req.model_dump())
        engine.display.calibration = calibration
        engine.display.force_full_redraw = True
        save_calibration(calibration)
        return calibration

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mock", action="store_true", help="render without the GC9A01 displays")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8100)
    parser.add_argument("--fps", type=float, default=30.0)
    args = parser.parse_args()
    uvicorn.run(create_app(args.mock, args.fps), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
