"""Hand-written independent fixture drawer (does NOT import panelproof.render).

Follows only the public conventions in docs/validation.md so that the raster verifier can be exercised
by images it did not see the renderer produce.
"""

import io
import math

from PIL import Image, ImageDraw, ImageFont

BG, MOD, RIM, FACE, INK, NEEDLE = (
    (226, 230, 235),
    (245, 247, 250),
    (60, 66, 78),
    (252, 252, 248),
    (30, 30, 35),
    (200, 40, 30),
)
_FONTS: dict[int, ImageFont.FreeTypeFont] = {}


def font(s):
    return _FONTS.setdefault(s, ImageFont.load_default(s))


def text(d, x, base, t, size, col=INK, left=False):
    f = font(size)
    w = sum(f.getlength(c) for c in t) + 2 * (len(t) - 1)
    cx = x if left else x - w / 2
    for c in t:
        d.text((round(cx), round(base)), c, font=f, fill=col, anchor="ls")
        cx += f.getlength(c) + 2


def cap(size):
    return -font(size).getbbox("0", anchor="ls")[1]


def dial(d, cx, cy, R, lo, hi, step, mpm, unit, tick_idx, caption, shift_deg=0.0):
    d.ellipse((cx - R, cy - R, cx + R, cy + R), fill=RIM)
    d.ellipse((cx - R + 6, cy - R + 6, cx + R - 6, cy + R - 6), fill=FACE)
    n = (hi - lo) // step * mpm
    for i in range(n + 1):
        a = math.radians(225 - 270 * i / n)
        major = i % mpm == 0
        r0, r1 = 0.90 * R, (0.74 if major else 0.82) * R
        d.line(
            (cx + r0 * math.cos(a), cy - r0 * math.sin(a), cx + r1 * math.cos(a), cy - r1 * math.sin(a)),
            fill=INK,
            width=3 if major else 2,
        )
        if major:
            sz = max(12, round(0.19 * R))
            px, py = cx + 0.52 * R * math.cos(a), cy - 0.52 * R * math.sin(a)
            text(d, px, py + cap(sz) / 2, str(lo + i // mpm * step), sz)
    us = max(11, round(0.15 * R))
    text(d, cx, cy + 0.74 * R + cap(us) / 2, unit, us)
    ang = 225 - 270 * tick_idx / n + shift_deg
    a = math.radians(ang)
    w = max(3, round(0.04 * R)) / 2
    tip = (cx + 0.72 * R * math.cos(a), cy - 0.72 * R * math.sin(a))
    p = math.radians(ang + 90)
    d.polygon(
        [(cx + w * math.cos(p), cy - w * math.sin(p)), tip, (cx - w * math.cos(p), cy + w * math.sin(p))], fill=NEEDLE
    )
    d.ellipse((cx - 13, cy - 13, cx + 13, cy + 13), fill=RIM)
    text(d, cx, cy + R + 28, caption, 18)


def lamp(d, x, y, name, on, color):
    if on:
        d.ellipse((x - 30, y - 30, x + 30, y + 30), fill=tuple((a + b) // 2 for a, b in zip(MOD, color, strict=True)))
    d.ellipse((x - 24, y - 24, x + 24, y + 24), fill=color if on else (150, 150, 155), outline=RIM, width=3)
    text(d, x, y + 54, name, 16)


def panel(
    inlet_tick=10,
    outlet_tick=27,
    run=True,
    alarm=False,
    inlet_unit="kPa",
    outlet_unit="kPa",
    scale=(0, 600, 100, 5),
    captions=("INLET", "OUTLET"),
    shift_in=0.0,
    shift_out=0.0,
    title="PUMP A",
):
    img = Image.new("RGB", (1280, 960), BG)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((136, 116, 1144, 844), radius=18, fill=MOD, outline=(120, 130, 145), width=3)
    text(d, 160, 160, title, 26, left=True)
    lo, hi, step, mpm = scale
    dial(d, 380, 450, 150, lo, hi, step, mpm, inlet_unit, inlet_tick, captions[0], shift_in)
    dial(d, 740, 450, 150, lo, hi, step, mpm, outlet_unit, outlet_tick, captions[1], shift_out)
    lamp(d, 1040, 388, "RUN", run, (40, 190, 80))
    lamp(d, 1040, 512, "ALARM", alarm, (230, 40, 40))
    return img


def png(img):
    b = io.BytesIO()
    img.save(b, "PNG")
    return b.getvalue()
