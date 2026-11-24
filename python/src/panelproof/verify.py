"""Independent raster verifier: recovers panel readings from PNG bytes only.

INDEPENDENCE CONTRACT (enforced by tests/test_verify.py):
  * the only input is the PNG byte string; nothing from scene.py, render.py, mutations.py,
    generator truth, masks, SVG or renderer coordinates is imported or read here
  * it relies only on the *public* conventions documented in docs/validation.md:
    dial sweep 225 -> -45 deg clockwise, tick/numeral/unit layout, 2 px text tracking,
    the public Pillow default font, lamp captions RUN/ALARM, and the public rules
  * geometry (dial centre/radius, tick angles, needle angle, lamp positions) is recovered
    from pixels with OpenCV contours, angular ink profiles and glyph-mask matching
"""

from __future__ import annotations

import hashlib
import math
from functools import lru_cache
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .interim_rules import THRESHOLD_MKPA
from .units import to_milli_kpa

VERIFIER_VERSION = "1.0.0"
TRACKING = 2
UNITS = ("kPa", "bar", "psi")
PUMP_LABELS = tuple(f"PUMP {c}" for c in "ABCDEF")
SNAP_FRAC = 0.30  # needle within 0.30 minor tick of a tick is snapped
TOLERANCES = {
    "needle_snap_ticks": SNAP_FRAC,
    "reading_uncertainty_ticks_snapped": 0.5,
    "text_iou_min": 0.72,
    "tick_angle_dev_deg": 1.5,
}


# ------------------------------------------------------------------ text-mask matching


@lru_cache(maxsize=64)
def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.load_default(size)


@lru_cache(maxsize=65536)
def _text_mask(text: str, size: int) -> np.ndarray:
    f = _font(size)
    width = int(sum(f.getlength(c) for c in text) + TRACKING * (len(text) - 1)) + 12
    im = Image.new("L", (width, size * 2 + 6), 0)
    d = ImageDraw.Draw(im)
    x = 6.0
    for ch in text:
        d.text((round(x), size + 2), ch, font=f, fill=255, anchor="ls")
        x += f.getlength(ch) + TRACKING
    a = np.asarray(im) >= 128
    ys, xs = np.where(a)
    return a[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]


@lru_cache(maxsize=65536)
def _approx_width(text: str, size: int) -> float:
    f = _font(size)
    return sum(f.getlength(c) for c in text) + TRACKING * (len(text) - 1)


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    best = 0.0
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            h, w = max(a.shape[0], b.shape[0]) + 2, max(a.shape[1], b.shape[1]) + 2
            pa = np.zeros((h, w), bool)
            pb = np.zeros((h, w), bool)
            pa[1 : 1 + a.shape[0], 1 : 1 + a.shape[1]] = a
            y0, x0 = 1 + dy, 1 + dx
            pb[y0 : y0 + b.shape[0], x0 : x0 + b.shape[1]] = b
            inter = np.logical_and(pa, pb).sum()
            union = np.logical_or(pa, pb).sum()
            best = max(best, inter / union if union else 0.0)
    return best


def _glyph_components(mask: np.ndarray) -> list[np.ndarray]:
    """Glyph crops left-to-right; components whose x-ranges overlap (i-dots) are merged."""
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    boxes = [
        [stats[k, 0], stats[k, 1], stats[k, 0] + stats[k, 2], stats[k, 1] + stats[k, 3]]
        for k in range(1, n)
        if stats[k, 4] >= 3
    ]
    boxes.sort()
    merged: list[list[int]] = []
    for bx in boxes:
        if merged and bx[0] < merged[-1][2] - 1 and bx[0] >= merged[-1][0]:
            m = merged[-1]
            m[0], m[1], m[2], m[3] = min(m[0], bx[0]), min(m[1], bx[1]), max(m[2], bx[2]), max(m[3], bx[3])
        else:
            merged.append(list(bx))
    return [mask[b[1] : b[3], b[0] : b[2]] for b in merged]


def match_text(mask: np.ndarray, candidates: list[str], sizes=range(9, 50)) -> tuple[str | None, float, int]:
    """Glyph-wise match of an ink mask against candidate strings; returns (text, mean_iou, size).

    Glyph shapes are compared individually, so sub-pixel advance rounding of the line does not matter.
    """
    ys, xs = np.where(mask)
    if len(ys) < 4:
        return None, 0.0, 0
    crop = mask[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    h = crop.shape[0]
    comps = _glyph_components(crop)
    cands = [t for t in candidates if len(t.replace(" ", "")) == len(comps)]
    if not cands:
        return None, 0.0, 0
    alphabet = sorted({c for t in cands for c in t if c != " "})
    best: tuple[str | None, float, int] = (None, 0.0, 0)
    for s in sizes:
        if abs(_text_mask("0", s).shape[0] - h) > 8:
            continue
        # per-component, per-char IoU
        ious = [
            {
                ch: _iou(g, _text_mask(ch, s))
                for ch in alphabet
                if abs(_text_mask(ch, s).shape[1] - g.shape[1]) <= 2
                and abs(_text_mask(ch, s).shape[0] - g.shape[0]) <= 2
            }
            for g in comps
        ]
        for t in cands:
            chars = t.replace(" ", "")
            vals = [ious[i].get(c, 0.0) for i, c in enumerate(chars)]
            sc = sum(vals) / len(vals)
            if min(vals) >= 0.55 and sc > best[1]:
                best = (t, sc, s)
    return best


def _ink(img: np.ndarray, rect: tuple[int, int, int, int], bg: tuple[int, ...]) -> np.ndarray:
    x0, y0, x1, y1 = rect
    sub = img[max(y0, 0) : y1, max(x0, 0) : x1].astype(np.int16)
    diff = np.abs(sub - np.array(bg, np.int16)).max(axis=2)
    if diff.size == 0 or diff.max() < 40:
        return np.zeros(diff.shape, bool)
    return diff >= 0.5 * diff.max()


def _mode_color(arr: np.ndarray) -> tuple[int, int, int]:
    flat = arr.reshape(-1, 3)
    key = flat[:, 0].astype(np.int64) * 65536 + flat[:, 1].astype(np.int64) * 256 + flat[:, 2]
    vals, counts = np.unique(key, return_counts=True)
    k = int(vals[counts.argmax()])
    return (k >> 16, (k >> 8) & 255, k & 255)


def _read_region(img: np.ndarray, rect: tuple[int, int, int, int], bg, candidates: list[str]):
    mask = _ink(img, rect, bg)
    text, score, size = match_text(mask, candidates)
    ok = text is not None and score >= TOLERANCES["text_iou_min"]
    ys, xs = np.where(mask)
    box = (
        [int(rect[0] + xs.min()), int(rect[1] + ys.min()), int(rect[0] + xs.max()), int(rect[1] + ys.max())]
        if len(ys)
        else None
    )
    return (text if ok else None), round(float(score), 3), box


@lru_cache(maxsize=1)
def _numeral_candidates() -> tuple[str, ...]:
    return tuple(str(i) for i in range(0, 1001))


# ------------------------------------------------------------------ geometry helpers


def _runs_circular(prof: np.ndarray, thr: float) -> list[float]:
    """Centroid angles (deg) of contiguous runs where profile >= thr (0.25 deg bins, circular)."""
    on = prof >= thr
    n = len(prof)
    if on.all() or not on.any():
        return []
    start = int(np.argmin(on))  # a False bin to start from
    runs, cur = [], []
    for k in range(1, n + 1):
        i = (start + k) % n
        if on[i]:
            cur.append(i if i >= start else i + n)
        elif cur:
            w = prof[np.array(cur) % n]
            runs.append(float((np.array(cur) * w).sum() / w.sum()) * 360.0 / n % 360.0)
            cur = []
    if cur:
        w = prof[np.array(cur) % n]
        runs.append(float((np.array(cur) * w).sum() / w.sum()) * 360.0 / n % 360.0)
    return runs


def _ang_profile(ink: np.ndarray, cx: float, cy: float, radii: np.ndarray, nbins: int = 1440) -> np.ndarray:
    ang = np.radians(np.arange(nbins) * 360.0 / nbins)
    xs = np.rint(cx + radii[None, :] * np.cos(ang)[:, None]).astype(int)
    ys = np.rint(cy - radii[None, :] * np.sin(ang)[:, None]).astype(int)
    h, w = ink.shape
    ok = (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h)
    vals = np.zeros(xs.shape)
    vals[ok] = ink[ys[ok], xs[ok]]
    return vals.mean(axis=1)


def k_round(m: float, spacing: float) -> float:
    return round(m / spacing) * spacing


def _read_gauge(img: np.ndarray, circle: tuple[float, float, float], module_fill) -> dict[str, Any]:
    cx, cy, R = circle
    rec: dict[str, Any] = {"center": [round(cx, 1), round(cy, 1)], "radius": round(R, 1), "reasons": []}
    pad = int(R + 4)
    x0, y0 = max(int(cx) - pad, 0), max(int(cy) - pad, 0)
    sub = img[y0 : int(cy) + pad, x0 : int(cx) + pad]
    lcx, lcy = cx - x0, cy - y0
    yy, xx = np.mgrid[0 : sub.shape[0], 0 : sub.shape[1]]
    rr = np.hypot(xx - lcx, yy - lcy)
    face = _mode_color(sub[(rr > 0.2 * R) & (rr < 0.9 * R)])
    rec["face_rgb_bgr"] = list(face)
    diff = np.abs(sub.astype(np.int16) - np.array(face, np.int16)).max(axis=2)
    ink = (diff > 60) & (rr < 0.93 * R)

    # ---- needle
    radii_n = np.arange(0.14 * R, 0.30 * R, 1.0)
    prof_n = _ang_profile(ink, lcx, lcy, radii_n, 720)
    if prof_n.max() < 0.7:
        rec["reasons"].append("needle_not_found")
        return rec
    plateau = np.where(prof_n >= 0.85 * prof_n.max())[0]
    # circular centroid of the plateau
    angs = np.radians(plateau * 0.5)
    needle = math.degrees(math.atan2(np.sin(angs).mean(), np.cos(angs).mean())) % 360.0
    rec["needle_angle_deg"] = round(needle, 2)

    # ---- ticks (all ticks at 0.83-0.89 R, majors also at 0.75-0.79 R)
    ink_d = cv2.dilate(ink.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    prof_t = _ang_profile(ink_d, lcx, lcy, np.linspace(0.83 * R, 0.89 * R, 9))
    ticks = sorted(t for t in ((225.0 - a) % 360.0 for a in _runs_circular(prof_t, 0.5)) if t <= 274.0)
    if len(ticks) < 6 or ticks[0] > 4 or abs(ticks[-1] - 270.0) > 4:
        rec["reasons"].append("scale_not_found")
        return rec
    n = len(ticks) - 1
    spacing = 270.0 / n
    if max(abs(t - k * spacing) for k, t in enumerate(ticks)) > TOLERANCES["tick_angle_dev_deg"]:
        rec["reasons"].append("tick_spacing_irregular")
        return rec
    prof_m = _ang_profile(ink_d, lcx, lcy, np.linspace(0.755 * R, 0.775 * R, 5))
    majors = sorted(m for m in ((225.0 - a) % 360.0 for a in _runs_circular(prof_m, 0.5)) if m <= 274.0 or m >= 358.0)
    majors = [m - 360.0 if m >= 358.0 else m for m in majors]
    # ticks near the needle are unreliable at the major band (needle tip reaches it): drop them,
    # then complete the arithmetic progression of major indices from the end ticks 0 and n.
    seen = {int(round(m / spacing)) for m in majors if abs(m - k_round(m, spacing)) <= 1.5}
    needle_rel = (225.0 - needle) % 360.0
    seen = {i for i in seen if abs(i * spacing - needle_rel) > 3.0}
    seen |= {0, n}
    from functools import reduce
    from math import gcd

    ordered = sorted(seen)
    mpm = reduce(gcd, [b - a for a, b in zip(ordered, ordered[1:], strict=False)])
    major_idx = list(range(0, n + 1, mpm))
    missing = [i for i in major_idx if i not in seen]
    if any(abs(i * spacing - needle_rel) > 3.0 and i not in (0, n) for i in missing) or mpm < 2:
        rec["reasons"].append("major_ticks_irregular")
        return rec
    rec["tick_count"] = n + 1
    rec["minor_per_major"] = mpm

    # ---- numerals at majors (skip those the needle may overlap)
    labels: list[tuple[int, int]] = []
    read_log = []
    for i, mi in enumerate(major_idx):
        a = 225.0 - mi * spacing
        d_needle = abs(((a - needle) + 180) % 360 - 180)
        if d_needle < 24:
            continue
        px, py = lcx + 0.52 * R * math.cos(math.radians(a)), lcy - 0.52 * R * math.sin(math.radians(a))
        win = np.zeros(ink.shape, bool)
        win[
            int(max(py - 0.14 * R, 0)) : int(py + 0.14 * R) + 1, int(max(px - 0.30 * R, 0)) : int(px + 0.30 * R) + 1
        ] = True
        sel = ink & win & (rr >= 0.32 * R) & (rr <= 0.74 * R)
        if not sel.any():
            continue
        dil = cv2.dilate(sel.astype(np.uint8), np.ones((3, 13), np.uint8))
        nl, lab = cv2.connectedComponents(dil)
        best, bd = None, 1e9
        for k in range(1, nl):
            ys, xs = np.where((lab == k) & sel)
            if len(ys) == 0:
                continue
            dist = math.hypot(xs.mean() - px, ys.mean() - py)
            if dist < bd:
                best, bd = (lab == k) & sel, dist
        if best is None or bd > 0.25 * R:
            continue
        text, score, _ = match_text(best, list(_numeral_candidates()), range(9, 40))
        read_log.append({"major": i, "text": text, "iou": round(float(score), 3)})
        if text is not None and score >= TOLERANCES["text_iou_min"]:
            labels.append((i, int(text)))
    rec["numerals"] = read_log
    if len(labels) < 3:
        rec["reasons"].append("numerals_unreadable")
        return rec
    (i0, v0), (i1, v1) = labels[0], labels[-1]
    step = (v1 - v0) / (i1 - i0)
    if step <= 0 or abs(step - round(step)) > 1e-9 or any(abs(v0 + step * (i - i0) - v) > 1e-9 for i, v in labels):
        rec["reasons"].append("numerals_inconsistent")
        return rec
    vmin = v0 - step * i0
    vmax = vmin + step * (len(major_idx) - 1)
    rec["scale"] = {"min": vmin, "max": vmax, "major_step": step, "minor_per_major": mpm}

    # ---- unit text below the hub
    ur = (int(lcx - 0.5 * R), int(lcy + 0.60 * R), int(lcx + 0.5 * R), int(lcy + 0.92 * R))
    usub = sub.copy()
    usub[rr >= 0.93 * R] = face
    unit, uscore, _ = _read_region(usub, ur, face, list(UNITS))
    if unit is None:
        rec["reasons"].append("unit_unreadable")
        return rec
    rec["unit"] = unit

    # ---- reading
    rel = (225.0 - needle) % 360.0
    if rel > 270.0 + 6.0:
        rec["reasons"].append("needle_outside_sweep")
        return rec
    idx_f = min(max(rel / 270.0 * n, 0.0), float(n))
    nearest = round(idx_f)
    frac = abs(idx_f - nearest)
    minor = step / mpm
    rec["tick_fraction_offset"] = round(frac, 3)
    if frac > SNAP_FRAC:
        rec["reasons"].append("needle_between_ticks")
        return rec
    reading = vmin + nearest * minor
    milli = int(round(reading * 1000))
    minor_milli = int(round(minor * 1000))
    rec["reading_milli"] = milli
    rec["minor_tick_milli"] = minor_milli
    rec["reading_mkpa"] = to_milli_kpa(milli, unit)
    rec["uncertainty_mkpa"] = to_milli_kpa(
        int(round(TOLERANCES["reading_uncertainty_ticks_snapped"] * minor_milli)), unit
    )
    rec["box"] = [int(cx - R), int(cy - R), int(cx + R), int(cy + R)]
    return rec


# ------------------------------------------------------------------ module / lamp detection


def _solve_pump(run: bool, delta: int, u: int) -> tuple[str | None, str | None]:
    if not run:
        return "STOPPED", None
    if delta - u >= THRESHOLD_MKPA:
        return "NORMAL", None
    if delta + u < THRESHOLD_MKPA:
        return "LOW_PRESSURE", None
    return None, "uncertainty_spans_class_boundary"


def verify_png(png: bytes) -> dict[str, Any]:
    arr = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    trace: dict[str, Any] = {
        "verifier_version": VERIFIER_VERSION,
        "image_sha256": hashlib.sha256(png).hexdigest(),
        "tolerances": TOLERANCES,
        "pumps": [],
        "rejections": [],
    }
    if arr is None:
        trace["rejections"].append("png_decode_failed")
        trace["status"] = "rejected"
        return trace
    h, w = arr.shape[:2]
    trace["image"] = {"width": w, "height": h}
    frame = np.concatenate(
        [arr[:8].reshape(-1, 3), arr[-8:].reshape(-1, 3), arr[:, :8].reshape(-1, 3), arr[:, -8:].reshape(-1, 3)]
    )
    bg = _mode_color(frame)
    diff = np.abs(arr.astype(np.int16) - np.array(bg, np.int16)).max(axis=2)
    mask = cv2.morphologyEx((diff > 10).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    mods = sorted((cv2.boundingRect(c) for c in cnts if cv2.contourArea(c) > 60000), key=lambda r: (r[1], r[0]))
    if not mods:
        trace["rejections"].append("no_panel_modules_found")
        trace["status"] = "rejected"
        return trace

    for mx, my, mw, mh in mods:
        fill = _mode_color(arr[my + 5 : my + mh - 5, mx + 5 : mx + mw - 5])
        inner = (mx + 6, my + 6, mx + mw - 6, my + mh - 6)
        sub = arr[inner[1] : inner[3], inner[0] : inner[2]].astype(np.int16)
        m2 = (np.abs(sub - np.array(fill, np.int16)).max(axis=2) > 12).astype(np.uint8)
        cs, _ = cv2.findContours(m2, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        gauges, lamps = [], []
        for c in cs:
            bx, by, bw, bh = cv2.boundingRect(c)
            area = cv2.contourArea(c)
            if abs(bw - bh) > 4 or bw < 30:
                continue
            fr = area / (math.pi * (bw / 2) ** 2)
            (ccx, ccy), cr = cv2.minEnclosingCircle(c)
            ccx, ccy = ccx + inner[0], ccy + inner[1]
            if bw >= 120 and fr >= 0.9:
                gauges.append((ccx, ccy, cr))
            elif 36 <= bw <= 66 and fr >= 0.85:
                lamps.append((ccx, ccy, cr))
        pump: dict[str, Any] = {"module_box": [mx, my, mx + mw, my + mh], "reasons": [], "gauges": {}, "lamps": {}}
        if len(gauges) != 2 or len(lamps) != 2:
            # merged / split modules or unexpected objects: never guess which instruments belong together
            pump["reasons"].append(f"unexpected_instrument_count:{len(gauges)}g/{len(lamps)}l")
        title, tscore, tbox = _read_region(arr, (mx + 8, my + 8, mx + int(mw * 0.6), my + 60), fill, list(PUMP_LABELS))
        pump["label"], pump["label_score"], pump["label_box"] = title, tscore, tbox
        if title is None:
            pump["reasons"].append("pump_label_unreadable")
        pump["pump_id"] = title.split()[-1] if title else None
        for gc in gauges:
            gx, gy, gr = gc
            cap, cscore, _ = _read_region(
                arr, (int(gx - gr), int(gy + gr + 6), int(gx + gr), int(gy + gr + 44)), fill, ["INLET", "OUTLET"]
            )
            rec = _read_gauge(arr, gc, fill)
            rec["caption"], rec["caption_score"] = cap, cscore
            if cap is None:
                pump["reasons"].append("gauge_caption_unreadable")
                continue
            if "reasons" in rec and rec["reasons"]:
                pump["reasons"].extend(f"{cap}:{r}" for r in rec["reasons"])
            pump["gauges"][cap] = rec
        for lc in lamps:
            lx, ly, lr = lc
            cap, cscore, _ = _read_region(
                arr, (int(lx - 60), int(ly + lr + 4), int(lx + 60), int(ly + lr + 40)), fill, ["RUN", "ALARM"]
            )
            if cap is None:
                pump["reasons"].append("lamp_caption_unreadable")
                continue
            patch = arr[int(ly) - 10 : int(ly) + 11, int(lx) - 10 : int(lx) + 11]
            hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV).reshape(-1, 3).mean(axis=0)
            sat, val = float(hsv[1]), float(hsv[2])
            state = "on" if sat >= 110 and val >= 140 else ("off" if sat <= 70 else None)
            if state is None:
                pump["reasons"].append(f"{cap}:lamp_state_ambiguous")
            pump["lamps"][cap] = {
                "state": state,
                "center": [round(lx, 1), round(ly, 1)],
                "sat": round(sat, 1),
                "val": round(val, 1),
                "caption_score": cscore,
            }
        for need in ("INLET", "OUTLET"):
            if need not in pump["gauges"]:
                pump["reasons"].append(f"missing_gauge_{need}")
        for need in ("RUN", "ALARM"):
            if need not in pump["lamps"]:
                pump["reasons"].append(f"missing_lamp_{need}")
        pump["verdict"] = "rejected"
        if not pump["reasons"] and all("reading_mkpa" in g for g in pump["gauges"].values()):
            run = pump["lamps"]["RUN"]["state"] == "on"
            alarm = pump["lamps"]["ALARM"]["state"] == "on"
            gi, go = pump["gauges"]["INLET"], pump["gauges"]["OUTLET"]
            delta = go["reading_mkpa"] - gi["reading_mkpa"]
            u = gi["uncertainty_mkpa"] + go["uncertainty_mkpa"]
            state, why = _solve_pump(run, delta, u)
            if why:
                pump["reasons"].append(why)
            else:
                pump["run"], pump["alarm"] = run, alarm
                pump["derived"] = {
                    "delta_mkpa": delta,
                    "delta_uncertainty_mkpa": u,
                    "state": state,
                    "expected_alarm": state == "LOW_PRESSURE",
                    "alarm_consistent": alarm == (state == "LOW_PRESSURE"),
                }
                pump["verdict"] = "verified"
        trace["pumps"].append(pump)
    n_ok = sum(p["verdict"] == "verified" for p in trace["pumps"])
    trace["coverage"] = {"modules": len(trace["pumps"]), "verified": n_ok}
    trace["status"] = "verified" if n_ok == len(trace["pumps"]) else "rejected"
    return trace
