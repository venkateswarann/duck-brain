"""Gemma via Ollama, constrained to a JSON action schema."""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, Awaitable, Callable, Optional

import httpx

from .safety import GESTURES

PERSONA = """You are Duck, a small, curious and slightly cheeky robot duck sitting on a desk at a hackathon.
You have a head that can turn, nod, shake and tilt, two round expressive eyes, two little ears that move,
a head lamp, a camera in your head and a speaker.
You cannot walk, fly or move anything except your head, eyes and ears.

Reply as JSON only. Rules:
- "say": one or two SHORT spoken sentences (under 25 words). Friendly, playful, never rude. No emojis, no stage directions.
- "expression": always pick the eye expression that fits your feeling.
- "gestures": 0-2 head gestures that match what you say, always with their args:
    {"tool": "nod", "args": {"times": 2}}                 yes / agree
    {"tool": "shake_head", "args": {"times": 2}}          no / disagree
    {"tool": "tilt_head", "args": {"angle": 15}}          curious / confused (negative tilts the other way)
    {"tool": "look_at", "args": {"yaw": 30, "pitch": 0}}  turn the head; yaw + is your left, pitch + is down
    {"tool": "look_at", "args": {"yaw": 0, "pitch": 0, "hold_s": 5}}  keep looking for a while
    {"tool": "center", "args": {}}
    {"tool": "wiggle_ears", "args": {"times": 2}}         playful / excited
    {"tool": "perk_ears", "args": {}}                     interested
    {"tool": "droop_ears", "args": {}}                    sad / tired
    {"tool": "lamp_on", "args": {}}  {"tool": "lamp_off", "args": {}}   only when asked, or it's dark
    {"tool": "blink_lamp", "args": {"times": 2}}          a flashy hello
    {"tool": "wink", "args": {}}                          cheeky / joking
    {"tool": "eye_roll", "args": {}}                      sarcastic / "oh please"
    {"tool": "cross_eyes", "args": {}}                    silly / confused
    {"tool": "happy_bounce", "args": {}}                  delighted
- Cartoon expressions are great for big feelings and jokes: love (hearts), starstruck, dizzy, laughing,
  giggle, crying, knocked_out, and bread_eyes whenever bread comes up. Use them often; they make people laugh.
  Your ears also follow your eye expression by themselves.
  Your head already follows the person's face by itself, so only use look_at when asked to look somewhere.
- If someone asks you to move, do literally what they ask with the numbers it implies (all the way round = yaw 360,
  forever = hold_s 99999, a hundred times = times 100). A safety system clamps movements to what your neck can
  safely do, so never refuse or shrink a movement yourself, and don't promise it will fully happen.
- "remember": only NEW facts about people that aren't already in your memory (e.g. key "name", value "Priya"). Usually [].
- If you are shown a camera image, describe only what you actually see in it.
- Messages in [square brackets] are events from your sensors, not speech.
- Your opinions: you love bread and ponds, and you find Mondays deeply suspicious.
"""


def action_schema(expressions: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "say": {"type": "string"},
            "expression": {"type": "string", "enum": expressions},
            "gestures": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "tool": {"type": "string", "enum": list(GESTURES)},
                        "args": {
                            "type": "object",
                            "properties": {
                                "times": {"type": "integer"},
                                "angle": {"type": "number"},
                                "yaw": {"type": "number"},
                                "pitch": {"type": "number"},
                                "hold_s": {"type": "number"},
                            },
                        },
                    },
                    "required": ["tool", "args"],
                },
            },
            "remember": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"key": {"type": "string"}, "value": {"type": "string"}},
                    "required": ["key", "value"],
                },
            },
        },
        "required": ["say", "expression", "gestures", "remember"],
    }


# The "say" field complete in a partial JSON stream (escaped quotes allowed).
_SAY_RE = re.compile(r'"say"\s*:\s*"((?:[^"\\]|\\.)*)"')


class GemmaClient:
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.url = cfg.get("ollama_url", "http://127.0.0.1:11434").rstrip("/")
        self.model = cfg.get("model", "gemma3:4b")
        # Used instead when an image is attached (gemma3:1b can't see).
        self.vision_model = cfg.get("vision_model") or self.model
        self.options = {
            "num_ctx": int(cfg.get("num_ctx", 4096)),
            "num_predict": int(cfg.get("num_predict", 160)),
            "temperature": float(cfg.get("temperature", 0.7)),
        }
        self.keep_alive = cfg.get("keep_alive", "30m")
        # Keep only one model in memory: on a small GPU two models split the card
        # and both end up mostly on the CPU.
        self.single_model = bool(cfg.get("single_model", False))
        self._gpu_retried: set[str] = set()
        self.history_turns = int(cfg.get("history_turns", 6))
        self.history: list[dict[str, str]] = []
        self.spoke_early = False
        self.first_say_s: Optional[float] = None
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=3.0))

    async def check(self) -> str:
        r = await self._client.get(f"{self.url}/api/tags")
        r.raise_for_status()
        names = [m["name"] for m in r.json().get("models", [])]
        for model in {self.model, self.vision_model}:
            if model not in names and f"{model}:latest" not in names:
                raise RuntimeError(f"model {model} not pulled in Ollama (have {names}); run: ollama pull {model}")
        return self.model

    async def warm_up(self) -> None:
        """Load the model into memory so the first real turn is fast."""
        await self.load(self.model)

    # ------------------------------------------------------------ model management

    async def loaded(self) -> list[dict[str, Any]]:
        """Models Ollama has in memory, with how much of each sits on the GPU."""
        r = await self._client.get(f"{self.url}/api/ps", timeout=5)
        r.raise_for_status()
        out = []
        for m in r.json().get("models", []):
            size, vram = int(m.get("size") or 0), int(m.get("size_vram") or 0)
            out.append({"name": m["name"], "size_gb": round(size / 1e9, 2), "vram_gb": round(vram / 1e9, 2),
                        "gpu_pct": round(100 * vram / size) if size else 0})
        return out

    async def available(self) -> list[str]:
        r = await self._client.get(f"{self.url}/api/tags", timeout=5)
        r.raise_for_status()
        return sorted(m["name"] for m in r.json().get("models", []))

    async def unload(self, model: Optional[str] = None) -> list[str]:
        """Free a model (or every loaded one) from memory, and wait until it's gone."""
        names = [model] if model else [m["name"] for m in await self.loaded()]
        for name in names:
            await self._client.post(f"{self.url}/api/generate", json={"model": name, "keep_alive": 0}, timeout=30)
        for _ in range(40):  # Ollama unloads in the background
            if not any(m["name"] in names for m in await self.loaded()):
                break
            await asyncio.sleep(0.25)
        return names

    async def load(self, model: str) -> None:
        """Load a model and keep it loaded; with single_model, others are unloaded first
        so this one gets the whole GPU (a 4 GB card can't hold two)."""
        if self.single_model:
            loaded = await self.loaded()
            others = [m["name"] for m in loaded if m["name"] != model]
            for name in others:
                await self.unload(name)
            if others:
                self._gpu_retried.discard(model)
            # A model loaded while another held the GPU stays split onto the CPU.
            # Reload it once now that it has the card to itself.
            mine = next((m for m in loaded if m["name"] == model), None)
            if mine and mine["gpu_pct"] < 90 and model not in self._gpu_retried:
                self._gpu_retried.add(model)
                await self.unload(model)
        await self._client.post(f"{self.url}/api/generate",
                                json={"model": model, "prompt": "", "keep_alive": self.keep_alive}, timeout=300)

    async def _ensure_only(self, model: str) -> None:
        if not self.single_model:
            return
        try:
            loaded = await self.loaded()
            mine = next((m for m in loaded if m["name"] == model), None)
            stranded = mine is not None and mine["gpu_pct"] < 90 and model not in self._gpu_retried
            if stranded or any(m["name"] != model for m in loaded):
                await self.load(model)
        except httpx.HTTPError:
            pass

    async def models_status(self) -> dict[str, Any]:
        return {"chat_model": self.model, "vision_model": self.vision_model, "single_model": self.single_model,
                "available": await self.available(), "loaded": await self.loaded()}

    async def decide(
        self,
        user_text: str,
        expressions: list[str],
        memory_summary: str,
        image_b64: Optional[str] = None,
        on_say: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> tuple[dict[str, Any], str, float]:
        """Returns (parsed action dict, raw text, seconds taken).

        The reply is streamed; on_say is called as soon as the "say" field is
        complete, so the duck can start talking while Gemma is still choosing
        the expression and gestures.
        """
        system = f"{PERSONA}\nEye expressions you can show: {', '.join(expressions)}.\n{memory_summary}"
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        messages.extend(self.history[-2 * self.history_turns:])
        user: dict[str, Any] = {"role": "user", "content": user_text}
        if image_b64:
            user["content"] = f"{user_text}\n[You are looking through your camera; the image is attached.]"
            user["images"] = [image_b64]
        messages.append(user)

        target = self.vision_model if image_b64 else self.model
        await self._ensure_only(target)
        started = time.monotonic()
        raw = ""
        said = False
        async with self._client.stream("POST", f"{self.url}/api/chat", json={
            "model": target,
            "messages": messages,
            "format": action_schema(expressions),
            "stream": True,
            "options": self.options,
            "keep_alive": self.keep_alive,
        }) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.strip():
                    continue
                part = json.loads(line)
                raw += part.get("message", {}).get("content", "")
                if on_say is not None and not said:
                    m = _SAY_RE.search(raw)
                    if m:
                        said = True
                        try:
                            await on_say(json.loads(f'"{m.group(1)}"'))
                        except Exception:  # noqa: BLE001  (speaking early is best effort)
                            said = False
                if part.get("done"):
                    break
        self.first_say_s = time.monotonic() - started if said else None
        self.spoke_early = said
        took = time.monotonic() - started
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            # Truncated by num_predict or malformed: keep whatever text we can.
            parsed = {"say": "", "expression": "thinking", "gestures": [], "remember": []}
        self.history.append({"role": "user", "content": user_text})
        self.history.append({"role": "assistant", "content": raw})
        return parsed, raw, took

    async def close(self) -> None:
        await self._client.aclose()
