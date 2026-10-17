"""Duck Brain: hear -> think (Gemma) -> check (safety) -> act (MCP) -> speak.

    uv run duck-brain                      # uses config.yaml
    uv run duck-brain --source text        # type to the duck in the trace UI
"""

from __future__ import annotations

import argparse
import asyncio
import os
import time
from pathlib import Path
from typing import Any, Optional

import uvicorn
import yaml
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .hearing import Transcriber, local_mic_loop, robot_mic_loop
from .llm import GemmaClient
from .memory import Memory
from .robot import Robot, RobotOffline
from .safety import HEAD_TOOLS, Decision, SafetyLayer
from .trace import Trace
from .tracking import FaceTracker

HERE = Path(__file__).resolve().parent
# Seconds per repetition with the robot's eased motion profile.
EST_GESTURE_S = {"nod": 1.3, "shake_head": 1.6, "tilt_head": 1.0, "look_at": 1.2, "center": 1.2,
                 "wiggle_ears": 0.4, "perk_ears": 0.4, "droop_ears": 0.5, "lamp_on": 0.0, "lamp_off": 0.0,
                 "blink_lamp": 0.4}


class Brain:
    def __init__(self, cfg: dict[str, Any], base_dir: Path) -> None:
        self.cfg = cfg
        self.trace = Trace()
        self.robot = Robot(cfg["robot"]["urls"], self.trace)
        self.safety = SafetyLayer(cfg.get("safety", {}))
        mem_cfg = cfg.get("memory", {})
        self.memory = Memory(str(base_dir / mem_cfg.get("path", "memory.json")), int(mem_cfg.get("max_items", 30)))
        self.llm = GemmaClient(cfg.get("llm", {}))
        sp = cfg.get("speech_in", {})
        self.stt = Transcriber(sp.get("stt_model", "small.en"), sp.get("stt_device", "auto"),
                               sp.get("stt_compute_type", "int8"), self.trace)
        self.vision_cfg = cfg.get("vision", {})
        self.stream = self.vision_cfg.get("stream", "head_cam")
        self.tracker = FaceTracker(cfg.get("tracking", {}), self.stream, self.robot, self.trace, self.on_new_face)
        self._turn_lock = asyncio.Lock()
        self._pending: Optional[tuple[str, str]] = None
        self.turns = 0
        self.breathing = bool(cfg.get("head", {}).get("breathing", True))
        self.ear_twitch = bool(cfg.get("head", {}).get("ear_twitch", True))
        self._estop_at = 0.0
        self.paused = False
        self._tracking_before_pause = self.tracker.enabled
        self.robot.on_connect = self._on_robot_connect

    # ------------------------------------------------------------------ startup

    async def start(self) -> list[asyncio.Task]:
        self.trace.set_state(model=self.llm.model, brain="on", expression="neutral", face=False,
                             tracking=self.tracker.enabled, link="offline")
        await self.robot.discover()
        await self.refresh_robot_info()
        await self.set_breathing(self.breathing)
        for attempt in (1, 2):  # Ollama may still be unloading a previous model
            try:
                await self.llm.check()
                self.trace.emit("llm", status="ok", detail=f"{self.llm.model} via Ollama, warming up")
                await self.llm.warm_up()
                break
            except Exception as exc:  # noqa: BLE001
                self.trace.emit("llm", status="error", detail=f"{type(exc).__name__}: {exc}"
                                + (" (retrying)" if attempt == 1 else " (use the model bar in the trace UI to load it)"))
                await asyncio.sleep(3)

        tasks = [
            asyncio.create_task(self.robot.heartbeat_loop(self.llm.model), name="heartbeat"),
            asyncio.create_task(self._refresh_loop(), name="refresh"),
            asyncio.create_task(self.robot.watch_loop(), name="robot-watch"),
            asyncio.create_task(self.tracker.run(), name="tracking"),
        ]
        source = self.cfg.get("speech_in", {}).get("source", "robot")
        if source in ("robot", "local"):
            await self.stt.load()
            loop = (robot_mic_loop(self.robot, self.stt, self.trace, self.on_speech_event, self.on_text)
                    if source == "robot" else
                    local_mic_loop(self.stt, self.trace, self.on_speech_event, self.on_text))
            tasks.append(asyncio.create_task(loop, name="hearing"))
        self.trace.emit("ready", detail=f"speech from: {source}; type in the trace UI any time")
        return tasks

    async def refresh_robot_info(self) -> None:
        try:
            exprs = await self.robot.get("/api/eyes/expressions")
            if isinstance(exprs, list) and exprs:
                self.safety.expressions = exprs
        except Exception:  # noqa: BLE001
            pass
        try:
            head = await self.robot.get("/api/head/state")
            if isinstance(head, dict) and head.get("limits"):
                self.safety.update_limits(head["limits"])
        except Exception:  # noqa: BLE001
            pass
        self.trace.set_state(expressions=self.safety.expressions)

    async def set_breathing(self, on: bool) -> None:
        try:
            r = await self.robot.post("/api/head/idle_motion", {"enabled": on})
            if isinstance(r, dict) and r.get("ok"):
                self.trace.set_state(breathing=on)
        except RobotOffline:
            pass
        if self.ear_twitch:
            try:
                # Ears twitch now and then while the duck is "breathing".
                await self.robot.post("/api/ears/idle", {"enabled": on})
            except Exception:  # noqa: BLE001  (no ears / older eyes service)
                pass

    async def _on_robot_connect(self) -> None:
        """DCS came (back) up, e.g. after a Pi 4 reboot: restore what the brain had switched on."""
        await self.refresh_robot_info()
        if self.breathing and not self.paused and time.monotonic() - self._estop_at > 10:
            await self.set_breathing(True)

    async def set_paused(self, paused: bool) -> None:
        """Brain off: ignore speech and faces (stop words still work). Brain on: back to normal."""
        if paused == self.paused:
            return
        self.paused = paused
        if paused:
            self._tracking_before_pause = self.tracker.enabled
            self.tracker.enabled = False
            self._pending = None
        else:
            self.tracker.enabled = self._tracking_before_pause
        self.trace.set_state(brain="paused" if paused else "on", tracking=self.tracker.enabled)
        self.trace.emit("brain", status="ok", detail="paused: ignoring speech and faces (stop words still work)"
                        if paused else "resumed")

    async def set_chat_model(self, model: str) -> None:
        self.llm.model = model
        self.trace.set_state(model=model)
        self.trace.emit("llm", status="ok", detail=f"chat model is now {model}; loading…")
        await self.llm.load(model)
        self.trace.emit("llm", status="ok", detail=f"{model} loaded")

    async def _refresh_loop(self) -> None:
        while True:
            await asyncio.sleep(30)
            await self.refresh_robot_info()

    # ------------------------------------------------------------------ reflexes

    async def on_speech_event(self, kind: str) -> None:
        if kind == "speech_start":
            self.trace.set_state(listening=True)
            await self._reflex_expression("listening")
        else:
            self.trace.set_state(listening=False)

    async def on_new_face(self) -> None:
        if self.paused:
            return
        await self.on_text("[A person just appeared in front of you. Greet them briefly.]", "camera")

    async def _reflex_expression(self, name: str) -> None:
        if name not in self.safety.expressions:
            return
        try:
            await self.robot.post("/api/eyes/expression", {"name": name})
            self.trace.set_state(expression=name)
        except RobotOffline:
            pass

    # ------------------------------------------------------------------ turns

    async def on_text(self, text: str, source: str) -> None:
        text = text.strip()
        if not text:
            return
        # Stop words act immediately, even mid-turn, without asking the model.
        if source != "camera" and self.safety.is_stop(text):
            self.trace.emit("heard", text=text, source=source)
            await self.estop(f"stop word in: “{text}”")
            return
        if self.paused:
            self.trace.emit("heard", text=text, source=source, status="ignored")
            return
        if self._turn_lock.locked():
            self._pending = (text, source)  # only the latest waiting utterance is kept
            return
        async with self._turn_lock:
            await self._turn(text, source)
            while self._pending:
                nxt, self._pending = self._pending, None
                await self._turn(*nxt)

    async def estop(self, reason: str) -> None:
        self._estop_at = time.monotonic()
        self.trace.set_state(breathing=False)
        self.trace.emit("safety", status="estop", detail=f"E-STOP ({reason}); bypassed the LLM")
        try:
            result = await self.robot.post("/api/estop")
            self.trace.emit("tool", tool="estop", status="ok", result=result)
        except RobotOffline as exc:
            self.trace.emit("tool", tool="estop", status="error", detail=str(exc))

    async def _turn(self, text: str, source: str) -> None:
        self.turns += 1
        started = time.monotonic()
        self.trace.emit("heard", text=text, source=source)
        await self._reflex_expression("thinking")

        image = None
        # A face greeting only needs a picture if it doesn't force swapping models
        # (on a small GPU with a separate vision model that costs several seconds).
        swap = self.llm.single_model and self.llm.vision_model != self.llm.model
        wants_image = (not swap) if source == "camera" else self._wants_vision(text)
        if wants_image:
            image = await self.robot.snapshot_b64(self.stream)
            self.trace.emit("vision", status="ok" if image else "error",
                            detail="looked through the head camera" if image else "no camera frame available",
                            image_b64=image)
        early_say: list[str] = []

        async def say_early(said: str) -> None:
            said = self.safety.review({"say": said}).say  # same length cap as the full review
            if not said:
                return
            await self.robot.post("/api/speech/say", {"text": said})
            early_say.append(said)
            self.trace.emit("say", text=said)

        try:
            raw, raw_text, took = await self.llm.decide(text, self.safety.expressions, self.memory.summary(), image,
                                                        on_say=say_early)
        except Exception as exc:  # noqa: BLE001
            self.trace.emit("llm", status="error", detail=f"Gemma failed: {exc}")
            await self._reflex_expression("neutral")
            return
        self.trace.emit("gemma", raw=raw_text, seconds=round(took, 2), vision=bool(image),
                        first_words_s=round(self.llm.first_say_s, 2) if self.llm.first_say_s else None)

        plan = self.safety.review(raw)
        for d in plan.all_decisions():
            if d.status != "ok":
                self.trace.emit("safety", status=d.status, action=d.action, args=_public(d.args), reasons=d.reasons)

        # Expression + speech first (one MCP session), then gestures in order.
        first: list[tuple[str, dict[str, Any]]] = [("eyes_set_expression", {"name": plan.expression.args["name"]})]
        if plan.say and not early_say:
            first.append(("speech_say", {"text": plan.say}))
            self.trace.emit("say", text=plan.say)
        self.trace.set_state(expression=plan.expression.args["name"])
        try:
            for r in await self.robot.call_tools(first):
                self._trace_tool(r)
            for d in plan.gestures:
                if d.status == "blocked" or d.tool is None:
                    continue
                await self._gesture(d)
        except RobotOffline as exc:
            self.trace.emit("robot", status="error", detail=f"couldn't act: {exc}")
        except Exception as exc:  # noqa: BLE001
            self.trace.emit("tool", status="error", detail=f"MCP call failed: {exc}")

        for key, value in plan.remember:
            if self.memory.remember(key, value):
                self.trace.emit("memory", detail=f"remembered {key} = {value}")
        self.trace.emit("turn", seconds=round(time.monotonic() - started, 2), turn=self.turns)
        # A STOP switches breathing off on the robot; bring it back once things are calm.
        if self.breathing and time.monotonic() - self._estop_at > 10:
            await self.set_breathing(True)

    async def _gesture(self, d: Decision) -> None:
        args = {k: v for k, v in d.args.items() if not k.startswith("_")}
        if "times" in args:
            args["times"] = int(args["times"])
        duration = EST_GESTURE_S.get(d.action, 0.6) * max(1, int(args.get("times", 1)))
        hold = d.args.get("_hold_s") or 0.0
        if d.tool in HEAD_TOOLS:
            self.tracker.pause(duration + hold + 1.0)
        (result,) = await self.robot.call_tools([(d.tool, args)])
        self._trace_tool(result, d)
        if d.action == "look_at":
            self.tracker.sync_pose(float(args.get("yaw", 0)), float(args.get("pitch", 0)))
        await asyncio.sleep(duration)
        if hold:
            await asyncio.sleep(hold)
            (back,) = await self.robot.call_tools([("head_center", {})])
            self._trace_tool(back)
            self.tracker.sync_pose(0.0, 0.0)

    def _trace_tool(self, r: dict[str, Any], decision: Optional[Decision] = None) -> None:
        res = r.get("result", {})
        status = "ok"
        reasons = list(decision.reasons) if decision else []
        if isinstance(res, dict):
            if res.get("ok") is False:
                status = "blocked"
                reasons += [f"robot: {x}" for x in res.get("reasons", [])] or [f"robot: {res.get('detail')}"]
            elif res.get("clamped"):
                status = "clamped"
                reasons += [f"robot: {x}" for x in res.get("reasons", [])]
            elif decision is not None and decision.status == "clamped":
                status = "clamped"
        self.trace.emit("tool", tool=r["tool"], args=r["args"], status=status, reasons=reasons, ms=r.get("ms"))

    def _wants_vision(self, text: str) -> bool:
        t = f" {text.lower()} "
        return any(f" {w}" in t for w in self.vision_cfg.get("trigger_words", []))


def _public(args: dict[str, Any]) -> dict[str, Any]:
    return {k.lstrip("_"): v for k, v in args.items() if v is not None}


# ---------------------------------------------------------------------- UI server


class SayReq(BaseModel):
    text: str


class ToggleReq(BaseModel):
    enabled: bool


class ModelReq(BaseModel):
    model: Optional[str] = None


def create_ui(brain: Brain) -> FastAPI:
    app = FastAPI(title="Duck Brain trace")

    @app.get("/")
    def index():
        return FileResponse(HERE / "ui" / "index.html")

    @app.post("/api/say")
    async def say(req: SayReq):
        asyncio.create_task(brain.on_text(req.text, "trace-ui"))
        return {"ok": True}

    @app.post("/api/estop")
    async def estop():
        await brain.estop("trace UI button")
        return {"ok": True}

    @app.post("/api/tracking")
    async def tracking(req: ToggleReq):
        brain.tracker.enabled = req.enabled
        brain.trace.set_state(tracking=req.enabled)
        return {"ok": True}

    @app.post("/api/brain")
    async def brain_toggle(req: ToggleReq):
        await brain.set_paused(not req.enabled)
        return {"ok": True, "enabled": not brain.paused}

    @app.get("/api/models")
    async def models():
        try:
            return await brain.llm.models_status()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(503, f"Ollama not answering: {exc}") from exc

    @app.post("/api/models/use")
    async def models_use(req: ModelReq):
        """Make this the chat model and load it (unloading others in single_model mode)."""
        if not req.model:
            raise HTTPException(400, "model required")
        await brain.set_chat_model(req.model)
        return await brain.llm.models_status()

    @app.post("/api/models/load")
    async def models_load(req: ModelReq):
        if not req.model:
            raise HTTPException(400, "model required")
        brain.trace.emit("llm", status="ok", detail=f"loading {req.model}…")
        await brain.llm.load(req.model)
        brain.trace.emit("llm", status="ok", detail=f"{req.model} loaded")
        return await brain.llm.models_status()

    @app.post("/api/models/unload")
    async def models_unload(req: ModelReq):
        names = await brain.llm.unload(req.model)
        brain.trace.emit("llm", status="ok", detail=f"unloaded {', '.join(names) or 'nothing'}")
        return await brain.llm.models_status()

    @app.get("/api/memory")
    async def memory():
        return brain.memory.items

    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        await sock.accept()
        q = brain.trace.subscribe()
        try:
            await sock.send_json({"type": "init", "events": list(brain.trace.events), "state": brain.trace.state})
            while True:
                await sock.send_json(await q.get())
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            brain.trace.unsubscribe(q)

    return app


async def amain(args: argparse.Namespace) -> None:
    cfg_path = Path(args.config).resolve()
    cfg = yaml.safe_load(cfg_path.read_text())
    if args.source:
        cfg.setdefault("speech_in", {})["source"] = args.source
    if args.robot_url:
        cfg["robot"]["urls"] = args.robot_url
    if args.no_tracking:
        cfg.setdefault("tracking", {})["enabled"] = False
    if args.model:
        cfg.setdefault("llm", {})["model"] = args.model

    ui_cfg = cfg.get("ui", {})
    host, port = ui_cfg.get("host", "127.0.0.1"), int(ui_cfg.get("port", 8300))
    # Two brains would both hear every utterance and both answer (and double the load).
    # The OS drops this lock when the process exits, even after a crash.
    import fcntl  # noqa: PLC0415

    lock = open(cfg_path.parent / ".duck-brain.lock", "w")  # noqa: SIM115  (held for the process lifetime)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("Another duck-brain is already running. Stop it first: pkill -f 'bin/duck-brain'") from None
    brain = Brain(cfg, cfg_path.parent)
    server = uvicorn.Server(uvicorn.Config(create_ui(brain), host=ui_cfg.get("host", "127.0.0.1"),
                                           port=int(ui_cfg.get("port", 8300)), log_level="warning"))
    ui_task = asyncio.create_task(server.serve(), name="ui")
    print(f"Trace UI: http://{ui_cfg.get('host', '127.0.0.1')}:{ui_cfg.get('port', 8300)}", flush=True)
    tasks = await brain.start()
    try:
        await asyncio.gather(ui_task, *tasks)
    finally:
        await brain.llm.close()
        await brain.robot.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=os.environ.get("DUCK_BRAIN_CONFIG", "config.yaml"))
    parser.add_argument("--source", choices=("robot", "local", "text"), help="override speech_in.source")
    parser.add_argument("--robot-url", nargs="+", help="override robot.urls")
    parser.add_argument("--model", help="override llm.model")
    parser.add_argument("--no-tracking", action="store_true")
    try:
        asyncio.run(amain(parser.parse_args()))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
