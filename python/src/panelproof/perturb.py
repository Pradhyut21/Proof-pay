"""Moderate-perturbation agreement for the raster verifier (PP-09 acceptance).

Outcomes per perturbed image: verified_correct | rejected (safe) | verified_wrong (false accept).
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .scene import scene_from_dict
from .validate import compare_trace_to_scene
from .verify import verify_png


def _enc(img: np.ndarray, jpeg: int | None = None) -> bytes:
    if jpeg:
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, jpeg])
        img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    ok, buf = cv2.imencode(".png", img)
    return buf.tobytes()


def apply(axis: str, img: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    f = img.astype(np.float32)
    if axis == "none":
        return img
    if axis == "brightness_+15%":
        return np.clip(f * 1.15, 0, 255).astype(np.uint8)
    if axis == "brightness_-15%":
        return np.clip(f * 0.85, 0, 255).astype(np.uint8)
    if axis == "gaussian_noise_sigma3":
        return np.clip(f + rng.normal(0, 3, f.shape), 0, 255).astype(np.uint8)
    if axis == "gaussian_blur_0.6":
        return cv2.GaussianBlur(img, (0, 0), 0.6)
    if axis == "jpeg_q90":
        return cv2.imdecode(cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])[1], cv2.IMREAD_COLOR)
    if axis == "rotate_1deg":
        m = cv2.getRotationMatrix2D((img.shape[1] / 2, img.shape[0] / 2), 1.0, 1.0)
        return cv2.warpAffine(img, m, (img.shape[1], img.shape[0]), borderMode=cv2.BORDER_REPLICATE)
    if axis == "scale_0.97":
        small = cv2.resize(img, None, fx=0.97, fy=0.97, interpolation=cv2.INTER_AREA)
        out = cv2.copyMakeBorder(small, 0, img.shape[0] - small.shape[0], 0, img.shape[1] - small.shape[1],
                                 cv2.BORDER_REPLICATE)
        return out
    if axis == "glare_over_panel":
        ov = img.copy()
        cv2.ellipse(ov, (img.shape[1] // 2, img.shape[0] // 2), (140, 50), 20, 0, 360, (255, 255, 255), -1)
        return cv2.addWeighted(ov, 0.25, img, 0.75, 0)
    raise ValueError(axis)


AXES = ["none", "brightness_+15%", "brightness_-15%", "gaussian_noise_sigma3", "gaussian_blur_0.6", "jpeg_q90",
        "rotate_1deg", "scale_0.97", "glare_over_panel"]


def _one(args: tuple[str, dict, str]) -> tuple[str, str, list[str]]:
    png_path, scene_d, axis = args
    img = cv2.imread(png_path)
    rng = np.random.default_rng(7)
    trace = verify_png(_enc(apply(axis, img, rng)))
    cmp_ = compare_trace_to_scene(trace, scene_from_dict(scene_d))
    reasons = [r for p in trace["pumps"] for r in p["reasons"]]
    if cmp_["agree"]:
        return axis, "verified_correct", reasons
    if trace["status"] == "verified":
        return axis, "verified_wrong", reasons
    # a partially verified scene with wrong values counts as wrong only if a verified pump disagrees
    wrong = any(p["verdict"] == "verified" and pc.get("errors") for p, pc in zip(trace["pumps"], cmp_["pumps"], strict=False))
    return axis, "verified_wrong" if wrong else "rejected", reasons


def run_perturbations(root: Path, limit: int = 60, workers: int = 4) -> dict[str, Any]:
    recs = [json.loads(line) for line in (root / "private" / "scenes.jsonl").read_text(encoding="utf-8").splitlines()][:limit]
    jobs = [(str(root / "images" / f"{r['scene_id']}.png"), r["scene"], ax) for r in recs for ax in AXES]
    with ProcessPoolExecutor(max_workers=workers) as ex:
        res = list(ex.map(_one, jobs, chunksize=8))
    by: dict[str, Counter] = defaultdict(Counter)
    why: dict[str, Counter] = defaultdict(Counter)
    for ax, out, reasons in res:
        by[ax][out] += 1
        why[ax].update(reasons)
    table = {}
    for ax in AXES:
        n = sum(by[ax].values())
        table[ax] = {"n": n, **{k: by[ax][k] for k in ("verified_correct", "rejected", "verified_wrong")},
                     "agreement_rate": round(by[ax]["verified_correct"] / n, 3),
                     "false_accept_rate": round(by[ax]["verified_wrong"] / n, 3),
                     "top_rejection_reasons": dict(why[ax].most_common(3))}
    return {"scenes": len(recs), "axes": table}
