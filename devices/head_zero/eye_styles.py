"""Cartoon eye styles and one-shot eye actions for the duck's round displays.

Styles replace the normal eye with an animated drawing (hearts, stars,
spirals...). They're picked through expressions.json ("style": "hearts"), so
Gemma and the API use them like any other expression. Actions are short
animations (wink, eye roll, cross-eyed...) layered on the current expression.

Everything is drawn inside a radius of ~95 px so the shell's bezel doesn't cut
it off, and animated from the time t (seconds since the style started).
"""

from __future__ import annotations

import math
from typing import Any, Callable, Optional

from PIL import Image, ImageDraw

W = H = 240
C = W // 2
BG = (0, 0, 0)


def _canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (W, H), BG)
    return img, ImageDraw.Draw(img)


def _heart(d: ImageDraw.ImageDraw, cx: float, cy: float, s: float, fill) -> None:
    pts = []
    for i in range(64):
        t = 2 * math.pi * i / 64
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        pts.append((cx + x * s, cy - y * s))
    d.polygon(pts, fill=fill)


def _star(d: ImageDraw.ImageDraw, cx: float, cy: float, r: float, rot: float, fill, points: int = 5) -> None:
    pts = []
    for i in range(points * 2):
        rr = r if i % 2 == 0 else r * 0.45
        a = rot + math.pi * i / points - math.pi / 2
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    d.polygon(pts, fill=fill)


def hearts(t: float, is_left: bool) -> Image.Image:
    img, d = _canvas()
    beat = 1.0 + 0.12 * max(0.0, math.sin(2 * math.pi * 1.6 * t)) ** 2  # lub-dub pulse
    _heart(d, C, C + 4, 5.2 * beat, (235, 40, 80))
    _heart(d, C - 22, C - 22, 1.0 * beat, (255, 170, 190))  # shine
    return img


def stars(t: float, is_left: bool) -> Image.Image:
    img, d = _canvas()
    spin = (1 if is_left else -1) * t * 1.5
    pulse = 1.0 + 0.08 * math.sin(2 * math.pi * 2 * t)
    _star(d, C, C, 88 * pulse, spin, (255, 210, 40))
    _star(d, C, C, 40 * pulse, spin + 0.6, (255, 245, 170))
    for i in range(3):  # sparkles orbiting
        a = t * 2.2 + i * 2 * math.pi / 3
        _star(d, C + 78 * math.cos(a), C + 78 * math.sin(a), 9, a, (255, 255, 255), 4)
    return img


def spiral(t: float, is_left: bool) -> Image.Image:
    img, d = _canvas()
    d.ellipse((C - 98, C - 98, C + 98, C + 98), fill=(245, 250, 255))
    turn = (1 if is_left else -1) * t * 5.0
    pts = []
    for i in range(260):
        a = i * 0.075
        r = 3 + i * 0.34
        pts.append((C + r * math.cos(a + turn), C + r * math.sin(a + turn)))
    d.line(pts, fill=(60, 40, 120), width=9, joint="curve")
    return img


def knocked_out(t: float, is_left: bool) -> Image.Image:
    img, d = _canvas()
    wob = 4 * math.sin(2 * math.pi * 0.8 * t)
    for a, b in (((-62, -62), (62, 62)), ((-62, 62), (62, -62))):
        d.line((C + a[0] + wob, C + a[1], C + b[0] + wob, C + b[1]), fill=(245, 250, 255), width=24)
    return img


def happy_arc(t: float, is_left: bool) -> Image.Image:
    """^ ^ : laughing with the eyes squeezed shut."""
    img, d = _canvas()
    bob = 6 * abs(math.sin(2 * math.pi * 2.2 * t))
    d.arc((C - 75, C - 40 - bob, C + 75, C + 110 - bob), 200, 340, fill=(245, 250, 255), width=26)
    return img


def giggle(t: float, is_left: bool) -> Image.Image:
    """> < : scrunched-up giggle (each eye points inward)."""
    img, d = _canvas()
    shake = 3 * math.sin(2 * math.pi * 7 * t)
    # Seen from the front the duck's right eye is on the viewer's left: "> <".
    tip, back = (C - 45, C + 45) if is_left else (C + 45, C - 45)
    d.line([(back + shake, C - 55), (tip + shake, C), (back + shake, C + 55)], fill=(245, 250, 255), width=24,
           joint="curve")
    return img


def bread(t: float, is_left: bool) -> Image.Image:
    """Bread-loaf eyes, for the duck's favourite thing."""
    img, d = _canvas()
    bob = 5 * math.sin(2 * math.pi * 1.2 * t)
    y = C + bob
    d.rounded_rectangle((C - 80, y - 30, C + 80, y + 70), radius=22, fill=(196, 132, 62))      # crust
    d.ellipse((C - 84, y - 78, C + 84, y + 20), fill=(196, 132, 62))                           # domed top
    d.rounded_rectangle((C - 66, y - 18, C + 66, y + 58), radius=16, fill=(245, 214, 160))     # crumb
    d.ellipse((C - 70, y - 64, C + 70, y + 6), fill=(245, 214, 160))
    for dx in (-36, 0, 36):  # scoring on top
        d.arc((C + dx - 18, y - 70, C + dx + 18, y - 40), 200, 340, fill=(160, 100, 40), width=6)
    return img


def loading(t: float, is_left: bool) -> Image.Image:
    img, d = _canvas()
    for i in range(8):
        a = 2 * math.pi * i / 8 + t * 4.0 * (1 if is_left else -1)
        fade = (i / 8)
        col = tuple(int(c * (0.25 + 0.75 * fade)) for c in (90, 200, 220))
        d.ellipse((C + 70 * math.cos(a) - 14, C + 70 * math.sin(a) - 14,
                   C + 70 * math.cos(a) + 14, C + 70 * math.sin(a) + 14), fill=col)
    return img


STYLES: dict[str, Callable[[float, bool], Image.Image]] = {
    "hearts": hearts,
    "stars": stars,
    "spiral": spiral,
    "knocked_out": knocked_out,
    "happy_arc": happy_arc,
    "giggle": giggle,
    "bread": bread,
    "loading": loading,
}


def tears(img: Image.Image, t: float, is_left: bool) -> Image.Image:
    """Overlay: tear drops rolling off the bottom of a normal (sad) eye."""
    d = ImageDraw.Draw(img)
    for k in range(2):
        phase = (t * 0.9 + k * 0.5) % 1.0
        x = C + (38 if is_left else -38) + k * (10 if is_left else -10)
        y = C + 55 + phase * 70
        r = 11
        d.ellipse((x - r, y - r, x + r, y + r), fill=(90, 170, 255))
        d.polygon([(x - r + 2, y - 3), (x + r - 2, y - 3), (x, y - 2.4 * r)], fill=(90, 170, 255))
    return img


OVERLAYS: dict[str, Callable[[Image.Image, float, bool], Image.Image]] = {"tears": tears}


# ------------------------------------------------------------------- actions

# name -> duration (s)
ACTIONS: dict[str, float] = {
    "wink": 0.7,
    "eye_roll": 1.4,
    "cross_eyes": 1.6,
    "look_around": 2.0,
    "happy_bounce": 1.3,
    "double_blink": 0.8,
}


def action_frame(name: str, t: float) -> Optional[dict[str, Any]]:
    """Per-eye overrides for time t into an action, or None when it's over.

    Keys: gaze_left / gaze_right (x, y in -1..1), blink_left / blink_right (0..1),
    lift (extra upward eye shift in px).
    """
    dur = ACTIONS.get(name)
    if dur is None or t > dur:
        return None
    p = t / dur
    bump = math.sin(math.pi * p)  # 0 -> 1 -> 0
    if name == "wink":
        return {"blink_left": min(1.0, bump * 1.4)}
    if name == "double_blink":
        return {"blink_left": abs(math.sin(2 * math.pi * p)), "blink_right": abs(math.sin(2 * math.pi * p))}
    if name == "eye_roll":
        a = math.pi + 2 * math.pi * p  # start left, go up and round
        g = (0.9 * math.cos(a), -0.6 - 0.35 * math.sin(a))
        return {"gaze_left": g, "gaze_right": g}
    if name == "cross_eyes":
        return {"gaze_left": (0.85 * bump, 0.1), "gaze_right": (-0.85 * bump, 0.1)}
    if name == "look_around":
        x = math.sin(2 * math.pi * 1.0 * p) * 0.95
        g = (x, -0.1)
        return {"gaze_left": g, "gaze_right": g}
    if name == "happy_bounce":
        return {"lift": -14 * abs(math.sin(3 * math.pi * p))}
    return None
