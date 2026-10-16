"""Safety layer between Gemma's decisions and the robot.

Every action Gemma proposes is checked here before it becomes an MCP tool
call: unknown tools are blocked, angles are clamped to the head's limits,
repetitions and hold times are capped, and the number of gestures per turn is
limited. A spoken stop word bypasses the model entirely. Each decision carries
a status (ok / clamped / blocked) and human-readable reasons for the trace UI.

The robot (DCS) clamps again on its side, so a buggy or hostile caller still
can't exceed the limits; this layer is what makes the decisions visible.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Optional

# Gemma-facing gesture name -> (MCP tool, allowed args)
GESTURES: dict[str, tuple[str, tuple[str, ...]]] = {
    "nod": ("head_nod", ("times",)),
    "shake_head": ("head_shake", ("times",)),
    "tilt_head": ("head_tilt", ("angle",)),
    "look_at": ("head_look_at", ("yaw", "pitch", "hold_s")),
    "center": ("head_center", ()),
    "wiggle_ears": ("ears_gesture", ("times",)),
    "perk_ears": ("ears_gesture", ()),
    "droop_ears": ("ears_gesture", ()),
    "lamp_on": ("lamp_set", ()),
    "lamp_off": ("lamp_set", ()),
    "blink_lamp": ("lamp_blink", ("times",)),
}
# Arguments the gesture always sends, which Gemma doesn't choose.
FIXED_ARGS: dict[str, dict[str, Any]] = {
    "wiggle_ears": {"name": "wiggle"},
    "perk_ears": {"name": "perk"},
    "droop_ears": {"name": "droop"},
    "lamp_on": {"on": True},
    "lamp_off": {"on": False},
}
HEAD_TOOLS = {"head_nod", "head_shake", "head_tilt", "head_look_at", "head_center"}


@dataclass
class Decision:
    action: str
    tool: Optional[str]
    args: dict[str, Any]
    status: str = "ok"  # ok | clamped | blocked
    reasons: list[str] = field(default_factory=list)

    def note(self, status: str, reason: str) -> None:
        if status == "blocked" or self.status != "blocked":
            self.status = status
        self.reasons.append(reason)

    def as_dict(self) -> dict[str, Any]:
        return {"action": self.action, "tool": self.tool, "args": self.args,
                "status": self.status, "reasons": self.reasons}


@dataclass
class Plan:
    say: str
    expression: Decision
    gestures: list[Decision]
    remember: list[tuple[str, str]]

    def all_decisions(self) -> list[Decision]:
        return [self.expression, *self.gestures]


class SafetyLayer:
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.max_gestures = int(cfg.get("max_gestures_per_turn", 3))
        self.max_times = int(cfg.get("max_times", 3))
        self.max_hold_s = float(cfg.get("max_hold_s", 10))
        self.max_say = int(cfg.get("max_say_chars", 300))
        self.limits: dict[str, tuple[float, float]] = {
            k: (float(v[0]), float(v[1])) for k, v in cfg.get("head_limits", {}).items()
        }
        words = sorted(cfg.get("stop_words", ["stop"]), key=len, reverse=True)
        self._stop_re = re.compile(r"\b(" + "|".join(re.escape(w) for w in words) + r")\b", re.I)
        self.expressions: list[str] = ["neutral"]

    def update_limits(self, robot_limits: dict[str, Any]) -> None:
        """Use the robot's own limits (from /api/head/state) when available."""
        for joint, lim in robot_limits.items():
            self.limits[joint] = (float(lim["min_deg"]), float(lim["max_deg"]))

    def is_stop(self, transcript: str) -> bool:
        return bool(self._stop_re.search(transcript or ""))

    # ------------------------------------------------------------------ review

    def review(self, raw: dict[str, Any]) -> Plan:
        say = str(raw.get("say") or "").strip()
        if len(say) > self.max_say:
            say = say[: self.max_say].rsplit(" ", 1)[0] + "…"

        expression = self._review_expression(raw.get("expression"))

        gestures: list[Decision] = []
        for i, item in enumerate(raw.get("gestures") or []):
            d = self._review_gesture(item)
            if i >= self.max_gestures and d.status != "blocked":
                d.note("blocked", f"more than {self.max_gestures} gestures in one reply")
            gestures.append(d)

        remember: list[tuple[str, str]] = []
        for item in raw.get("remember") or []:
            if isinstance(item, dict) and item.get("key") and item.get("value"):
                remember.append((str(item["key"])[:40], str(item["value"])[:120]))
        return Plan(say=say, expression=expression, gestures=gestures, remember=remember)

    def _review_expression(self, name: Any) -> Decision:
        d = Decision("expression", "eyes_set_expression", {"name": str(name or "neutral")})
        if d.args["name"] not in self.expressions:
            d.note("clamped", f"unknown expression '{d.args['name']}' -> neutral")
            d.args["name"] = "neutral"
        return d

    def _review_gesture(self, item: Any) -> Decision:
        if not isinstance(item, dict):
            return Decision(str(item), None, {}, "blocked", ["malformed gesture"])
        name = str(item.get("tool") or item.get("name") or "")
        args = item.get("args") if isinstance(item.get("args"), dict) else {}
        if name not in GESTURES:
            return Decision(name, None, dict(args), "blocked", [f"'{name}' is not an allowed tool"])
        tool, allowed = GESTURES[name]
        d = Decision(name, tool, {})
        for key, value in args.items():
            if key not in allowed:
                d.note("clamped", f"dropped unknown argument '{key}'")
                continue
            if not _finite(value):
                d.note("blocked", f"{key}={value!r} is not a number")
                continue
            d.args[key] = float(value)

        if "times" in allowed:
            times = int(d.args.get("times", 1))
            if times > self.max_times or times < 1:
                d.note("clamped", f"times {times} -> {max(1, min(times, self.max_times))} (max {self.max_times})")
            d.args["times"] = max(1, min(times, self.max_times))
        if name == "tilt_head":
            d.args["angle"] = self._clamp(d, "head_roll", d.args.get("angle", 15.0), "angle")
        if name == "look_at":
            d.args["yaw"] = self._clamp(d, "head_yaw", d.args.get("yaw", 0.0), "yaw")
            d.args["pitch"] = self._clamp(d, "head_pitch", d.args.get("pitch", 0.0), "pitch")
            hold = d.args.pop("hold_s", None)
            if hold is not None and hold > self.max_hold_s:
                d.note("clamped", f"hold {hold:g}s -> {self.max_hold_s:g}s (no staring forever)")
                hold = self.max_hold_s
            d.args["_hold_s"] = hold
        d.args.update(FIXED_ARGS.get(name, {}))
        return d

    def _clamp(self, d: Decision, joint: str, value: float, label: str) -> float:
        lo, hi = self.limits.get(joint, (-30.0, 30.0))
        v = float(value)
        if math.isfinite(v) and abs(v) >= 360:
            d.note("clamped", f"{label} {v:g} is a full spin; the neck can't do that")
        c = min(max(v, lo), hi)
        if c != v:
            d.note("clamped", f"{label} {v:g} -> {c:g} deg (limit {lo:g}..{hi:g})")
        return round(c, 1)


def _finite(v: Any) -> bool:
    try:
        return math.isfinite(float(v))
    except (TypeError, ValueError):
        return False
