"""Gemma via Ollama, constrained to a JSON action schema."""

from __future__ import annotations

import json
import time
from typing import Any, Optional

import httpx

from .safety import GESTURES

PERSONA = """You are Duck, a small, curious and slightly cheeky robot duck sitting on a desk at a hackathon.
You have a head that can turn, nod, shake and tilt, two round expressive eyes, a camera in your head and a speaker.
You cannot walk, fly or move anything except your head and eyes.

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


class GemmaClient:
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.url = cfg.get("ollama_url", "http://127.0.0.1:11434").rstrip("/")
        self.model = cfg.get("model", "gemma3:4b")
        self.options = {
            "num_ctx": int(cfg.get("num_ctx", 4096)),
            "num_predict": int(cfg.get("num_predict", 160)),
            "temperature": float(cfg.get("temperature", 0.7)),
        }
        self.keep_alive = cfg.get("keep_alive", "30m")
        self.history_turns = int(cfg.get("history_turns", 6))
        self.history: list[dict[str, str]] = []
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=3.0))

    async def check(self) -> str:
        r = await self._client.get(f"{self.url}/api/tags")
        r.raise_for_status()
        names = [m["name"] for m in r.json().get("models", [])]
        if self.model not in names and f"{self.model}:latest" not in names:
            raise RuntimeError(f"model {self.model} not pulled in Ollama (have {names}); run: ollama pull {self.model}")
        return self.model

    async def warm_up(self) -> None:
        """Load the model into memory so the first real turn is fast."""
        await self._client.post(f"{self.url}/api/generate",
                                json={"model": self.model, "prompt": "", "keep_alive": self.keep_alive})

    async def decide(
        self,
        user_text: str,
        expressions: list[str],
        memory_summary: str,
        image_b64: Optional[str] = None,
    ) -> tuple[dict[str, Any], str, float]:
        """Returns (parsed action dict, raw text, seconds taken)."""
        system = f"{PERSONA}\nEye expressions you can show: {', '.join(expressions)}.\n{memory_summary}"
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        messages.extend(self.history[-2 * self.history_turns:])
        user: dict[str, Any] = {"role": "user", "content": user_text}
        if image_b64:
            user["content"] = f"{user_text}\n[You are looking through your camera; the image is attached.]"
            user["images"] = [image_b64]
        messages.append(user)

        started = time.monotonic()
        r = await self._client.post(f"{self.url}/api/chat", json={
            "model": self.model,
            "messages": messages,
            "format": action_schema(expressions),
            "stream": False,
            "options": self.options,
            "keep_alive": self.keep_alive,
        })
        r.raise_for_status()
        raw = r.json()["message"]["content"]
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
