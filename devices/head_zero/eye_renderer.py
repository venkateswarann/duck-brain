"""Eye drawing for the two GC9A01 round displays.

The drawing code is lifted from emo1.py (angled eyelids, pupil dilation,
anime highlights). Expression presets live in expressions.json so new ones
can be added without touching code.
"""

from __future__ import annotations

import json
import os
from typing import Any

from PIL import Image, ImageChops, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))

WIDTH = HEIGHT = 240
CENTER = WIDTH // 2

SCLERA_COLOR = (245, 250, 255)
IRIS_COLOR = (55, 175, 185)
PUPIL_COLOR = (0, 0, 0)
HIGHLIGHT_COLOR = (255, 255, 255)
BG_COLOR = (0, 0, 0)

SCLERA_RADIUS = 115
IRIS_RADIUS = 75
BASE_PUPIL_RADIUS = 40
MAX_OFFSET = SCLERA_RADIUS - IRIS_RADIUS - 5

LID_KEYS = ("up_in", "up_out", "dn_in", "dn_out", "pupil")

CALIBRATION_FILE = os.path.join(HERE, "eye_config.json")
EXPRESSIONS_FILE = os.path.join(HERE, "expressions.json")
DEFAULT_CALIBRATION = {
    "left": {"rotation": 0, "offset_x": 0, "offset_y": 0},
    "right": {"rotation": 0, "offset_x": 0, "offset_y": 0},
}


def load_expressions(path: str = EXPRESSIONS_FILE) -> dict[str, dict[str, Any]]:
    with open(path, "r") as f:
        data = json.load(f)
    for name, preset in data.items():
        missing = [k for k in LID_KEYS if k not in preset]
        if missing:
            raise ValueError(f"expression '{name}' is missing {missing}")
    return data


def load_calibration(path: str = CALIBRATION_FILE) -> dict[str, dict[str, int]]:
    cfg: dict[str, dict[str, int]] = {}
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                cfg = json.load(f)
        except Exception:  # noqa: BLE001
            cfg = {}
    for eye in ("left", "right"):
        merged = dict(DEFAULT_CALIBRATION[eye])
        merged.update(cfg.get(eye, {}))
        cfg[eye] = merged
    return cfg


def save_calibration(cfg: dict[str, dict[str, int]], path: str = CALIBRATION_FILE) -> None:
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)


def apply_transform(img, rotation=0, offset_x=0, offset_y=0):
    if rotation:
        img = img.rotate(-rotation, resample=Image.BILINEAR, fillcolor=BG_COLOR)
    if offset_x or offset_y:
        canvas = Image.new("RGB", img.size, BG_COLOR)
        canvas.paste(img, (offset_x, offset_y))
        img = canvas
    return img


def draw_eye(offset_x, offset_y, state, blink_factor=0.0, is_left=True):
    """Render a single eye with dynamic eyelids and pupils."""
    img = Image.new("RGB", (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # 1. Sclera
    draw.ellipse((CENTER - SCLERA_RADIUS, CENTER - SCLERA_RADIUS,
                  CENTER + SCLERA_RADIUS, CENTER + SCLERA_RADIUS), fill=SCLERA_COLOR)

    # 2. Iris & pupil (pupil scales with the emotion)
    ix = CENTER + int(offset_x)
    iy = CENTER + int(offset_y)
    draw.ellipse((ix - IRIS_RADIUS, iy - IRIS_RADIUS, ix + IRIS_RADIUS, iy + IRIS_RADIUS), fill=IRIS_COLOR)
    pr = int(BASE_PUPIL_RADIUS * state["pupil"])
    draw.ellipse((ix - pr, iy - pr, ix + pr, iy + pr), fill=PUPIL_COLOR)

    # 3. Highlights
    hl_primary_r = int(BASE_PUPIL_RADIUS * 0.35)
    p_off_x, p_off_y = int(pr * 0.65), int(pr * 0.65)
    draw.ellipse((ix - p_off_x - hl_primary_r, iy - p_off_y - hl_primary_r,
                  ix - p_off_x + hl_primary_r, iy - p_off_y + hl_primary_r), fill=HIGHLIGHT_COLOR)
    hl_secondary_r = int(BASE_PUPIL_RADIUS * 0.15)
    s_off_x, s_off_y = int(pr * 0.4), int(pr * 0.4)
    draw.ellipse((ix + s_off_x - hl_secondary_r, iy + s_off_y - hl_secondary_r,
                  ix + s_off_x + hl_secondary_r, iy + s_off_y + hl_secondary_r), fill=HIGHLIGHT_COLOR)

    # 4. Angled eyelids
    if is_left:
        up_l_val, up_r_val = state["up_out"], state["up_in"]
        dn_l_val, dn_r_val = state["dn_out"], state["dn_in"]
    else:
        up_l_val, up_r_val = state["up_in"], state["up_out"]
        dn_l_val, dn_r_val = state["dn_in"], state["dn_out"]

    lid_radius = 120
    up_l_y = CENTER - (1.0 - up_l_val) * lid_radius
    up_r_y = CENTER - (1.0 - up_r_val) * lid_radius
    up_l_y += (CENTER - up_l_y) * blink_factor
    up_r_y += (CENTER - up_r_y) * blink_factor

    dn_l_y = CENTER + (1.0 - dn_l_val) * lid_radius
    dn_r_y = CENTER + (1.0 - dn_r_val) * lid_radius
    dn_l_y -= (dn_l_y - CENTER) * blink_factor
    dn_r_y -= (dn_r_y - CENTER) * blink_factor

    draw.polygon([(0, 0), (WIDTH, 0), (WIDTH, up_r_y), (0, up_l_y)], fill=BG_COLOR)
    draw.polygon([(0, HEIGHT), (WIDTH, HEIGHT), (WIDTH, dn_r_y), (0, dn_l_y)], fill=BG_COLOR)

    return img


class DualDisplay:
    """Pushes eye frames to both screens, sending only the changed rectangle."""

    def __init__(self, left: Any, right: Any, calibration: dict[str, dict[str, int]]) -> None:
        self.left = left
        self.right = right
        self.calibration = calibration
        self._last_left = None
        self._last_right = None
        self.force_full_redraw = True

    def show(self, raw_left, raw_right) -> None:
        left_img = apply_transform(raw_left, **self.calibration["left"])
        right_img = apply_transform(raw_right, **self.calibration["right"])

        if self.force_full_redraw or self._last_left is None:
            self.left.image(left_img)
            self.right.image(right_img)
            self.force_full_redraw = False
        else:
            for screen, last, img in ((self.left, self._last_left, left_img),
                                      (self.right, self._last_right, right_img)):
                box = ImageChops.difference(last, img).getbbox()
                if box:
                    screen.update_partial(img.crop(box), box[0], box[1])

        self._last_left = left_img
        self._last_right = right_img

    def cleanup(self) -> None:
        self.left.cleanup()
        self.right.cleanup()


class NullScreen:
    """Stands in for a GC9A01 when running without hardware (--mock)."""

    def image(self, img) -> None:
        pass

    def update_partial(self, img, x, y) -> None:
        pass

    def cleanup(self) -> None:
        pass


def open_displays(mock: bool, calibration: dict[str, dict[str, int]]) -> DualDisplay:
    if mock:
        return DualDisplay(NullScreen(), NullScreen(), calibration)
    from gc9a01_driver import GC9A01  # noqa: PLC0415  (needs spidev + RPi.GPIO)

    # Wiring from emo1.py: SPI0 CE0/CE1, DC 9/23, RST 25/24.
    left = GC9A01(spi_bus=0, spi_device=0, dc_pin=9, rst_pin=25, speed_hz=60000000)
    right = GC9A01(spi_bus=0, spi_device=1, dc_pin=23, rst_pin=24, speed_hz=60000000)
    return DualDisplay(left, right, calibration)
