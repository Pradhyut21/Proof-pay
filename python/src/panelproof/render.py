"""Deterministic CPU renderer (Pillow). Pure function of the Scene; emits metadata-free PNGs.

Public visual conventions (also what the raster verifier relies on, without importing this module):
  * dial sweep: first tick at 225 deg (lower-left), last tick at -45 deg, clockwise, 270 deg total
  * tick marks at 0.74-0.90 R, numerals at 0.52 R for each major tick, unit text below the hub
  * needle is a single bar from the hub to 0.72 R, no tail; RUN/ALARM lamps are filled discs with captions
  * all text uses the Pillow default font (Aileron, CC0) with 2 px tracking
"""

from __future__ import annotations

import io
import math
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from .scene import CANVAS_H, CANVAS_W, Gauge, Pump, Scene

START_DEG, SWEEP_DEG = 225.0, 270.0
TRACKING = 2

THEMES: dict[str, dict[str, tuple[int, int, int]]] = {
    "daylight": dict(
        bg=(226, 230, 235),
        module=(245, 247, 250),
        border=(120, 130, 145),
        rim=(60, 66, 78),
        face=(252, 252, 248),
        tick=(30, 30, 35),
        text=(25, 28, 35),
        needle=(200, 40, 30),
        lamp_off=(150, 150, 155),
        run_on=(40, 190, 80),
        alarm_on=(230, 40, 40),
    ),
    "slate": dict(
        bg=(28, 32, 40),
        module=(52, 60, 74),
        border=(110, 120, 140),
        rim=(16, 18, 24),
        face=(232, 236, 240),
        tick=(20, 20, 26),
        text=(235, 238, 245),
        needle=(240, 120, 20),
        lamp_off=(100, 102, 108),
        run_on=(60, 220, 110),
        alarm_on=(255, 70, 60),
    ),
    "sand": dict(
        bg=(214, 205, 188),
        module=(238, 230, 214),
        border=(130, 115, 90),
        rim=(90, 70, 45),
        face=(255, 252, 240),
        tick=(50, 40, 30),
        text=(45, 35, 25),
        needle=(170, 30, 40),
        lamp_off=(160, 150, 135),
        run_on=(50, 170, 70),
        alarm_on=(215, 45, 40),
    ),
    "teal": dict(
        bg=(200, 222, 224),
        module=(228, 242, 243),
        border=(60, 110, 118),
        rim=(20, 80, 90),
        face=(250, 254, 254),
        tick=(15, 40, 46),
        text=(12, 40, 46),
        needle=(215, 60, 20),
        lamp_off=(140, 160, 162),
        run_on=(30, 180, 90),
        alarm_on=(225, 45, 55),
    ),
}
COVER = (110, 110, 116)


@lru_cache(maxsize=64)
def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.load_default(size)


def text_width(text: str, size: int) -> float:
    f = font(size)
    return sum(f.getlength(c) for c in text) + TRACKING * (len(text) - 1)


def draw_text(
    d: ImageDraw.ImageDraw,
    x: float,
    baseline: float,
    text: str,
    size: int,
    fill: tuple[int, int, int],
    align: str = "center",
) -> tuple[int, int, int, int]:
    """Draw tracked text; returns the (x0, y0, x1, y1) ink box estimate."""
    f = font(size)
    total = text_width(text, size)
    cx = x - total / 2 if align == "center" else x
    for ch in text:
        d.text((round(cx), round(baseline)), ch, font=f, fill=fill, anchor="ls")
        cx += f.getlength(ch) + TRACKING
    top = f.getbbox("H", anchor="ls")[1]
    x0 = round(x - total / 2) if align == "center" else round(x)
    return (x0, round(baseline + top), round(x0 + total), round(baseline))


def cap_height(size: int) -> int:
    return -font(size).getbbox("0", anchor="ls")[1]


def angle_for(g: Gauge, value_milli: int | None = None) -> float:
    v = g.value_milli if value_milli is None else value_milli
    f = (v - g.min_milli) / (g.max_milli - g.min_milli)
    return START_DEG - SWEEP_DEG * f


def polar(cx: float, cy: float, r: float, deg: float) -> tuple[float, float]:
    a = math.radians(deg)
    return cx + r * math.cos(a), cy - r * math.sin(a)


def draw_gauge(d: ImageDraw.ImageDraw, g: Gauge, th: dict, fs: float, covered: bool) -> None:
    cx, cy, R = g.cx, g.cy, g.r
    d.ellipse((cx - R, cy - R, cx + R, cy + R), fill=th["rim"])
    if covered:
        d.ellipse((cx - R + 2, cy - R + 2, cx + R - 2, cy + R - 2), fill=COVER)
        for k in range(-R, R, 14):
            d.line((cx + k - R // 2, cy - R // 2, cx + k + R // 2, cy + R // 2), fill=(150, 150, 156), width=3)
        return
    rf = R - 6
    d.ellipse((cx - rf, cy - rf, cx + rf, cy + rf), fill=th["face"])
    n = g.n_minor
    for i in range(n + 1):
        major = i % g.minor_per_major == 0
        ang = START_DEG - SWEEP_DEG * i / n
        p0 = polar(cx, cy, 0.90 * R, ang)
        p1 = polar(cx, cy, (0.74 if major else 0.82) * R, ang)
        d.line((p0, p1), fill=th["tick"], width=3 if major else 2)
        if major:
            val = (g.min_milli + i * g.minor_milli) // 1000
            size = max(12, round(0.19 * R * fs))
            px, py = polar(cx, cy, 0.52 * R, ang)
            draw_text(d, px, py + cap_height(size) / 2, str(val), size, th["tick"])
    usize = max(11, round(0.15 * R * fs))
    draw_text(d, cx, cy + 0.74 * R + cap_height(usize) / 2, g.unit, usize, th["tick"])
    ang = angle_for(g)
    w = max(3, round(0.04 * R)) / 2
    tip = polar(cx, cy, 0.72 * R, ang)
    px, py = math.cos(math.radians(ang + 90)), -math.sin(math.radians(ang + 90))
    base0, base1 = (cx + px * w, cy + py * w), (cx - px * w, cy - py * w)
    d.polygon([base0, tip, base1], fill=th["needle"])
    hr = max(4, round(0.09 * R))
    d.ellipse((cx - hr, cy - hr, cx + hr, cy + hr), fill=th["rim"])


def blend(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(a[i] * (1 - t) + b[i] * t) for i in range(3))  # type: ignore[return-value]


def draw_pump(d: ImageDraw.ImageDraw, p: Pump, th: dict, fs: float) -> None:
    x0, y0, x1, y1 = p.module
    d.rounded_rectangle((x0, y0, x1, y1), radius=18, fill=th["module"], outline=th["border"], width=3)
    draw_text(d, x0 + 24, y0 + 44, p.label, round(26 * fs), th["text"], align="left")
    for g in p.gauges:
        draw_gauge(d, g, th, fs, g.role in p.covered)
        csize = round(18 * fs)
        draw_text(d, g.cx, g.cy + g.r + 28, g.role, csize, th["text"])
    for name, (lx, ly, lr) in p.lamps.items():
        on = p.run if name == "RUN" else p.alarm
        on_col = th["run_on"] if name == "RUN" else th["alarm_on"]
        if on:
            d.ellipse((lx - lr - 6, ly - lr - 6, lx + lr + 6, ly + lr + 6), fill=blend(th["module"], on_col, 0.35))
        d.ellipse(
            (lx - lr, ly - lr, lx + lr, ly + lr), fill=on_col if on else th["lamp_off"], outline=th["rim"], width=3
        )
        draw_text(d, lx, ly + lr + 30, name, round(16 * fs), th["text"])


def render_scene(scene: Scene) -> Image.Image:
    th = THEMES[scene.theme]
    img = Image.new("RGB", (CANVAS_W, CANVAS_H), th["bg"])
    d = ImageDraw.Draw(img)
    for p in scene.pumps:
        draw_pump(d, p, th, scene.font_scale)
    if scene.glare:
        gx, gy, rx, ry = scene.glare
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).ellipse((gx - rx, gy - ry, gx + rx, gy + ry), fill=(255, 255, 255, 90))
        img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")
    return img


def png_bytes(img: Image.Image) -> bytes:
    """Metadata-stripped, deterministic PNG."""
    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=6)
    return buf.getvalue()


def evidence_annotations(scene: Scene) -> list[dict]:
    """Private evidence regions (generator-side only; never given to the raster verifier)."""
    out: list[dict] = []
    for p in scene.pumps:
        out.append({"pump": p.pump_id, "kind": "module", "box": list(p.module)})
        for g in p.gauges:
            tip = polar(g.cx, g.cy, 0.72 * g.r, angle_for(g))
            out.append(
                {
                    "pump": p.pump_id,
                    "kind": f"gauge_{g.role.lower()}",
                    "box": [g.cx - g.r, g.cy - g.r, g.cx + g.r, g.cy + g.r],
                    "needle_tip": [round(tip[0], 1), round(tip[1], 1)],
                }
            )
        for name, (lx, ly, lr) in p.lamps.items():
            out.append({"pump": p.pump_id, "kind": f"lamp_{name.lower()}", "box": [lx - lr, ly - lr, lx + lr, ly + lr]})
    return out


def check_layout(scene: Scene) -> list[str]:
    """Return layout violations: bounds, overlap, legibility."""
    errs: list[str] = []
    boxes: list[tuple[str, tuple[float, float, float, float]]] = []
    for p in scene.pumps:
        x0, y0, x1, y1 = p.module
        if x0 < 0 or y0 < 0 or x1 > CANVAS_W or y1 > CANVAS_H:
            errs.append(f"{p.pump_id}: module out of bounds")
        boxes.append((f"{p.pump_id}:module", (x0, y0, x1, y1)))
        for g in p.gauges:
            if g.r < 70:
                errs.append(f"{p.pump_id}:{g.role}: gauge radius {g.r} too small")
            b = (g.cx - g.r, g.cy - g.r, g.cx + g.r, g.cy + g.r + 40)
            if b[0] < x0 or b[2] > x1 or b[1] < y0 or b[3] > y1:
                errs.append(f"{p.pump_id}:{g.role}: gauge outside module")
            boxes.append((f"{p.pump_id}:{g.role}", b))
        for name, (lx, ly, lr) in p.lamps.items():
            b = (lx - lr - 6, ly - lr - 6, lx + lr + 6, ly + lr + 40)
            if b[0] < x0 or b[2] > x1 or b[1] < y0 or b[3] > y1:
                errs.append(f"{p.pump_id}:{name}: lamp outside module")
            boxes.append((f"{p.pump_id}:{name}", b))
    inner = [(n, b) for n, b in boxes if not n.endswith(":module")]
    for i, (na, a) in enumerate(inner):
        for nb, b in inner[i + 1 :]:
            if not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]):
                errs.append(f"overlap {na} / {nb}")
    mods = [(n, b) for n, b in boxes if n.endswith(":module")]
    for i, (na, a) in enumerate(mods):
        for nb, b in mods[i + 1 :]:
            if not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]):
                errs.append(f"module overlap {na} / {nb}")
    return errs
