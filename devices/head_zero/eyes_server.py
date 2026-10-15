#!/usr/bin/env python3
"""HTTP API for the duck's eyes (runs on the head Pi Zero 2 W).

    python3 eyes_server.py                 # real GC9A01 displays
    python3 eyes_server.py --mock          # no hardware, preview only

DCS on the Pi 4 proxies these routes under /api/eyes/*.
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


class IdleReq(BaseModel):
    enabled: bool


class EyeCalibration(BaseModel):
    rotation: int = 0
    offset_x: int = 0
    offset_y: int = 0


class CalibrationReq(BaseModel):
    left: EyeCalibration
    right: EyeCalibration


def create_app(mock: bool, fps: float) -> FastAPI:
    calibration = load_calibration()
    expressions = load_expressions()
    engine = EyeEngine(open_displays(mock, calibration), expressions, fps=fps)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        engine.start()
        yield
        engine.stop()

    app = FastAPI(title="Duck Eyes", lifespan=lifespan)

    @app.get("/health")
    def health():
        return {"ok": True, "mock": mock, "frames": engine.frames}

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
        return engine.state()

    @app.post("/look")
    def look(req: LookReq):
        engine.look(req.x, req.y, req.hold_s)
        return engine.state()

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
