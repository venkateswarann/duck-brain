"""Liar's Duck game server: the duck deals, narrates and judges; players use their phones.

    uv run duck-game                      # http://<laptop-ip>:8400  (phones)
                                          # http://127.0.0.1:8400/host  (big screen with QR code)

The game state lives here, on the laptop, so a robot reboot never loses a game:
the duck just goes quiet and picks up again when DCS is back.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import socket
import time
from pathlib import Path
from typing import Any, Optional

import httpx
import uvicorn
import yaml
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from ..robot import Robot
from ..trace import Trace
from .liars import RANK_NAMES, GameError, LiarsGame, rank_word

HERE = Path(__file__).parent
TURN_S = 30.0


def lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def plural(rank: str) -> str:
    word = RANK_NAMES.get(rank, rank)
    return f"{word}es" if word == "six" else f"{word}s"


class DuckHost:
    """The duck's side of the game: voice, eyes and the odd head gesture, best effort."""

    def __init__(self, robot: Robot, brain_url: str) -> None:
        self.robot = robot
        self.brain_url = brain_url.rstrip("/")
        self.queue: asyncio.Queue = asyncio.Queue()

    async def run(self) -> None:
        while True:
            path, body = await self.queue.get()
            if path == "__pause__":
                await asyncio.sleep(body)
                continue
            try:
                await self.robot.post(path, body)
            except Exception:  # noqa: BLE001  (the game goes on without the duck)
                pass

    def _send(self, path: str, body: Any = None) -> None:
        self.queue.put_nowait((path, body))

    def pause(self, seconds: float) -> None:
        """Hold the next duck action back (for suspense)."""
        self._send("__pause__", seconds)

    def say(self, text: str) -> None:
        self._send("/api/speech/say", {"text": text})

    def eyes(self, name: str, hold_s: Optional[float] = None) -> None:
        self._send("/api/eyes/expression", {"name": name, **({"hold_s": hold_s} if hold_s else {})})

    def action(self, name: str) -> None:
        self._send("/api/eyes/action", {"name": name})

    def card(self, left: str, right: str = "", hold_s: float = 30, color=(245, 250, 255),
             left_sub: str = "", right_sub: str = "") -> None:
        self._send("/api/eyes/card", {"left": left, "right": right, "hold_s": hold_s, "color": list(color),
                                       "left_sub": left_sub, "right_sub": right_sub})

    def head(self, gesture: str, times: int = 1) -> None:
        self._send(f"/api/head/{gesture}", {"times": times})

    async def brain(self, enabled: bool) -> None:
        """Pause the conversation brain during a game so the duck doesn't chat over itself."""
        try:
            async with httpx.AsyncClient(timeout=2) as http:
                await http.post(f"{self.brain_url}/api/brain", json={"enabled": enabled})
        except httpx.HTTPError:
            pass


class Table:
    def __init__(self, duck: DuckHost, join_url: str, hand_size: int, challenge_s: float) -> None:
        self.game = LiarsGame(hand_size=hand_size, challenge_s=challenge_s)
        self.duck = duck
        self.join_url = join_url
        self.lock = asyncio.Lock()
        self.sockets: dict[WebSocket, Optional[str]] = {}  # socket -> player id (None = host/spectator)
        self.log: list[dict[str, Any]] = []
        self.turn_started = time.monotonic()
        self.hurried = False
        self.reveal_until = 0.0

    # ------------------------------------------------------------ broadcast

    def event(self, text: str, kind: str = "info") -> None:
        self.log.append({"t": time.time(), "text": text, "kind": kind})
        self.log = self.log[-40:]

    async def broadcast(self) -> None:
        pub = self.game.public()
        pub.update({"log": self.log[-15:], "join_url": self.join_url,
                    "turn_deadline": self.turn_started + TURN_S if self.game.phase == "turn" else None,
                    "now": time.monotonic()})
        dead = []
        for ws, pid in list(self.sockets.items()):
            try:
                msg = {"type": "state", "state": pub}
                if pid:
                    msg["me"] = self.game.private(pid)
                await ws.send_json(msg)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            self.sockets.pop(ws, None)

    def name(self, pid: Optional[str]) -> str:
        p = self.game.players.get(pid or "")
        return p.name if p else "someone"

    # ------------------------------------------------------------ flow

    def _new_turn(self) -> None:
        self.turn_started = time.monotonic()
        self.hurried = False
        cur = self.game.current
        if cur is None:
            return
        rank = self.game.rank
        self.duck.card(rank, rank, hold_s=TURN_S + 10, left_sub="play", right_sub="play")
        self.duck.say(random.choice([f"{cur.name}, play your {plural(rank)}!", f"{cur.name}! {plural(rank).capitalize()}, please.",
                                     f"Your turn, {cur.name}. {plural(rank).capitalize()}!"]))
        self.event(f"{cur.name}'s turn: play {plural(rank)}", "turn")

    async def start(self) -> None:
        self.game.start()
        self.log = []
        await self.duck.brain(False)
        names = ", ".join(p.name for p in self.game.players.values())
        self.duck.eyes("starstruck", 3)
        self.duck.say(f"Welcome to Liar's Duck! Players: {names}. I'm dealing {self.game.hand_size} cards each. "
                      "Lie all you like, but if someone shouts quack, I check!")
        self.event(f"Round {self.game.round}: dealt {self.game.hand_size} cards each", "start")
        self._new_turn()

    async def on_play(self, pid: str, cards: list[int], auto: bool = False) -> None:
        play = self.game.auto_play() if auto else self.game.play(pid, cards)
        who = self.name(play.player_id)
        n = len(play.cards)
        self.duck.card(f"x{n}", play.rank, hold_s=self.game.challenge_s + 1, color=(255, 200, 60),
                       left_sub="claimed", right_sub="")
        self.duck.eyes("suspicious", self.game.challenge_s)
        claim = rank_word(play.rank, n)
        self.duck.say(random.choice([f"{who} says {claim}. Anyone?", f"{claim.capitalize()}, says {who}. Hmm.",
                                     f"{who} claims {claim}. Quack if you doubt it!"]))
        self.event(f"{who} {'(timed out) ' if auto else ''}plays {n} card{'s' if n > 1 else ''}, claiming {claim}", "claim")

    async def on_quack(self, caller: str) -> None:
        liar_id = self.game.last_play.player_id if self.game.last_play else None
        v = self.game.quack(caller)
        who, by = self.name(liar_id), self.name(caller)
        self.reveal_until = time.monotonic() + 4.5
        shown = " ".join(f"{c['rank']}{c['suit']}" for c in v["cards"])
        self.duck.eyes("loading", 3)
        self.duck.say(f"Quack! {by} calls {who} a liar! Let's see...")
        self.duck.pause(2.6)
        if v["honest"]:
            self.duck.eyes("laughing", 3)
            self.duck.head("nod")
            self.duck.say(random.choice([f"Honest! {by}, you take the pile, all {v['picked_up']} cards!",
                                         f"Nope, {who} told the truth. {by} picks up {v['picked_up']}!"]))
            self.event(f"QUACK by {by}: {who} was honest ({shown}). {by} picks up {v['picked_up']}", "honest")
        else:
            self.duck.eyes("angry", 3)
            self.duck.head("shake")
            self.duck.say(random.choice([f"Busted! {who} was bluffing! Take all {v['picked_up']} cards!",
                                         f"Liar, liar! {who}, pick up {v['picked_up']}. Nice catch, {by}!"]))
            self.event(f"QUACK by {by}: {who} LIED ({shown}). {who} picks up {v['picked_up']}", "busted")
        await self._after_resolve()

    async def on_window_closed(self) -> None:
        info = self.game.close_challenge()
        if info is None:
            return
        self.event(f"No quack. {self.name(info['player'])}'s claim stands", "info")
        await self._after_resolve()

    async def _after_resolve(self) -> None:
        if self.game.phase == "over":
            w = self.name(self.game.winner)
            self.duck.eyes("starstruck", 5)
            self.duck.action("happy_bounce")
            self.duck.card("WIN", "", hold_s=8, color=(255, 210, 40))
            ranking = sorted(self.game.players.values(), key=lambda p: -p.score)
            self.duck.say(f"{w} wins! Quack quack! Leader on points: {ranking[0].name} with {ranking[0].score}.")
            self.event(f"{w} WINS round {self.game.round}!", "win")
            await self.duck.brain(True)
        else:
            self._new_turn()

    # ------------------------------------------------------------ ticking

    async def tick_loop(self) -> None:
        while True:
            await asyncio.sleep(0.2)
            async with self.lock:
                g = self.game
                now = time.monotonic()
                changed = False
                if g.phase == "challenge" and now >= g.challenge_until:
                    await self.on_window_closed()
                    changed = True
                elif g.phase == "turn" and g.current is not None:
                    left = self.turn_started + TURN_S - now
                    if left < 10 and not self.hurried:
                        self.hurried = True
                        self.duck.action("eye_roll")
                        self.duck.say(f"Tick tock, {g.current.name}!")
                        changed = True
                    if left <= 0 and g.current.hand:
                        await self.on_play(g.current.id, [], auto=True)
                        changed = True
                if changed:
                    await self.broadcast()


# ---------------------------------------------------------------------- app


class JoinReq(BaseModel):
    name: str


def create_app(table: Table) -> FastAPI:
    app = FastAPI(title="Liar's Duck")

    @app.get("/")
    def play_page():
        return FileResponse(HERE / "static" / "play.html")

    @app.get("/host")
    def host_page():
        return FileResponse(HERE / "static" / "host.html")

    @app.get("/qr.svg")
    def qr():
        import segno  # noqa: PLC0415

        svg = segno.make(table.join_url, error="m").svg_inline(scale=8, dark="#111", light="#fff")
        return Response(svg, media_type="image/svg+xml")

    @app.post("/api/join")
    async def join(req: JoinReq):
        async with table.lock:
            try:
                p = table.game.join(req.name)
            except GameError as exc:
                raise HTTPException(400, str(exc)) from exc
            table.event(f"{p.name} joined", "join")
            if table.game.phase == "lobby":
                table.duck.say(random.choice([f"Welcome, {p.name}!", f"Hello {p.name}! Quack.", f"{p.name} is in!"]))
            await table.broadcast()
        return {"token": p.token, "id": p.id, "name": p.name}

    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        await sock.accept()
        token = sock.query_params.get("token", "")
        player = table.game.by_token(token) if token else None
        table.sockets[sock] = player.id if player else None
        if player:
            player.connected = True
        await table.broadcast()
        try:
            while True:
                msg = await sock.receive_json()
                kind = msg.get("type")
                async with table.lock:
                    try:
                        if kind == "play" and player:
                            await table.on_play(player.id, [int(i) for i in msg.get("cards", [])])
                        elif kind == "quack" and player:
                            await table.on_quack(player.id)
                        elif kind == "start" and table.game.phase in ("lobby", "over"):
                            await table.start()
                        elif kind == "reset" and player is None:  # host only
                            scores = {pid: 0 for pid in table.game.players}
                            for pid in scores:
                                table.game.players[pid].score = 0
                            table.game.phase = "lobby"
                            table.event("Scores reset", "info")
                        elif kind == "kick" and player is None:
                            table.game.remove(str(msg.get("id")))
                    except GameError as exc:
                        await sock.send_json({"type": "error", "detail": str(exc)})
                    await table.broadcast()
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            table.sockets.pop(sock, None)
            if player and not any(pid == player.id for pid in table.sockets.values()):
                player.connected = False
            await table.broadcast()

    return app


async def amain(args: argparse.Namespace) -> None:
    cfg_path = Path(args.config).resolve()
    cfg = yaml.safe_load(cfg_path.read_text())
    urls = args.robot_url or cfg["robot"]["urls"]
    for extra in ("http://rpi1.local:8000", "http://rpi1:8000", "http://100.117.2.11:8000"):
        if extra not in urls:
            urls.append(extra)
    robot = Robot(urls, Trace())
    await robot.discover()
    duck = DuckHost(robot, args.brain_url)
    join_url = args.public_url or f"http://{lan_ip()}:{args.port}/"
    table = Table(duck, join_url, args.hand_size, args.challenge_s)
    app = create_app(table)
    server = uvicorn.Server(uvicorn.Config(app, host=args.host, port=args.port, log_level="warning"))
    print(f"Liar's Duck: players join at {join_url}  |  host screen: http://127.0.0.1:{args.port}/host", flush=True)
    print(f"Robot: {robot.base or 'not found yet (the game works without it; the duck joins when DCS is up)'}", flush=True)
    await asyncio.gather(server.serve(), table.tick_loop(), duck.run(), robot.watch_loop())


def main() -> None:
    parser = argparse.ArgumentParser(description="Liar's Duck: a bluffing card game hosted by the duck")
    parser.add_argument("--config", default=os.environ.get("DUCK_BRAIN_CONFIG", "config.yaml"))
    parser.add_argument("--robot-url", nargs="+")
    parser.add_argument("--brain-url", default="http://127.0.0.1:8300", help="paused during a game")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8400)
    parser.add_argument("--public-url", help="join URL for the QR code (default: this laptop's LAN IP)")
    parser.add_argument("--hand-size", type=int, default=7)
    parser.add_argument("--challenge-s", type=float, default=6.0)
    args = parser.parse_args()
    try:
        asyncio.run(amain(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
