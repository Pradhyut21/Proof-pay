"""Moderate-perturbation agreement for the raster verifier (PP-09 acceptance).

Outcomes per perturbed image: verified_correct | rejected (safe) | verified_wrong (false accept).
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .scene import canonical_json, config_hash, load_config, scene_from_dict
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
    if axis in ("rotate_1deg", "rotate_minus_1deg"):
        angle = 1.0 if axis == "rotate_1deg" else -1.0
        m = cv2.getRotationMatrix2D((img.shape[1] / 2, img.shape[0] / 2), angle, 1.0)
        return cv2.warpAffine(img, m, (img.shape[1], img.shape[0]), borderMode=cv2.BORDER_REPLICATE)
    if axis == "scale_0.97":
        small = cv2.resize(img, None, fx=0.97, fy=0.97, interpolation=cv2.INTER_AREA)
        out = cv2.copyMakeBorder(
            small, 0, img.shape[0] - small.shape[0], 0, img.shape[1] - small.shape[1], cv2.BORDER_REPLICATE
        )
        return out
    if axis == "glare_over_panel":
        ov = img.copy()
        cv2.ellipse(ov, (img.shape[1] // 2, img.shape[0] // 2), (140, 50), 20, 0, 360, (255, 255, 255), -1)
        return cv2.addWeighted(ov, 0.25, img, 0.75, 0)
    raise ValueError(axis)


AXES = [
    "none",
    "brightness_+15%",
    "brightness_-15%",
    "gaussian_noise_sigma3",
    "gaussian_blur_0.6",
    "jpeg_q90",
    "rotate_1deg",
    "scale_0.97",
    "glare_over_panel",
]
SUPPORTED_AXES = (*AXES, "rotate_minus_1deg")


def _one(args: tuple[str, dict, str, bool]) -> tuple[str, str, list[str], bool, bool, bool]:
    png_path, scene_d, axis, recover = args
    img = cv2.imread(png_path)
    image_key = hashlib.sha256(Path(png_path).name.encode()).digest()[:4]
    rng = np.random.default_rng([7, int.from_bytes(image_key, "big")])
    trace = verify_png(_enc(apply(axis, img, rng)), recover_small_distortions=recover)
    scene = scene_from_dict(scene_d)
    cmp_ = compare_trace_to_scene(trace, scene)
    verified = [pump for pump in cmp_["pumps"] if pump["verdict"] == "verified"]
    wrong = any(pump["errors"] for pump in verified) or sum(
        pump["verdict"] == "verified" for pump in trace["pumps"]
    ) > len(verified)
    non_exact = wrong or any(
        gauge["reading_milli"] != scene.pump(pump["pump_id"]).gauge(role).value_milli
        for pump in trace["pumps"]
        if pump["verdict"] == "verified"
        for role, gauge in pump["gauges"].items()
    )
    reasons = [*trace["rejections"], *(reason for pump in trace["pumps"] for reason in pump["reasons"])]
    normalized = "normalization" in trace
    if cmp_["agree"]:
        return axis, "verified_correct", reasons, not non_exact, non_exact, normalized
    wrong = wrong or trace["status"] == "verified"
    return axis, "verified_wrong" if wrong else "rejected", reasons, False, non_exact or wrong, normalized


def _base_scenes(root: Path, limit: int, generator_config: Path | None) -> list[tuple[str, dict[str, Any]]]:
    """Original (unedited) base scenes of a bundle as (png path, scene dict).

    A bundle does not store scene truth; it is regenerated from the private per-task seed, which is deterministic.
    """
    from .scene import generate_scene

    cfg = load_config(generator_config)
    seen: set[str] = set()
    out: list[tuple[str, dict[str, Any]]] = []
    for line in (root / "private" / "answers.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r.get("variant_edit") is not None or r["variant_kind"] != "base" or r["scene_id"] in seen:
            continue
        seen.add(r["scene_id"])
        scene = generate_scene(r["seed"], cfg)
        if scene.scene_id != r["scene_id"]:
            raise RuntimeError(f"scene {r['scene_id']} does not regenerate from its seed")
        out.append((str(root / r["image"]), scene.to_dict()))
        if len(out) >= limit:
            break
    return out


def run_perturbations(
    root: Path,
    limit: int = 60,
    workers: int = 4,
    *,
    axes: list[str] | None = None,
    generator_config: Path | None = None,
    recover_small_distortions: bool = False,
) -> dict[str, Any]:
    selected = axes or AXES
    if limit < 1 or workers < 1 or len(set(selected)) != len(selected):
        raise ValueError("Expected positive scene and worker counts and distinct perturbation axes.")
    scenes = _base_scenes(root, limit, generator_config)
    if not scenes:
        raise ValueError("The dataset has no base scenes to test.")
    source = json.loads((root / "manifest.json").read_bytes())
    sample = [Path(image).name for image, _ in scenes]
    jobs = [(img, scene, ax, recover_small_distortions) for img, scene in scenes for ax in selected]
    with ProcessPoolExecutor(max_workers=workers) as ex:
        res = list(ex.map(_one, jobs, chunksize=8))
    by: dict[str, Counter] = defaultdict(Counter)
    why: dict[str, Counter] = defaultdict(Counter)
    for ax, out, reasons, exact, non_exact, normalized in res:
        by[ax][out] += 1
        by[ax]["verified_exact"] += exact
        by[ax]["accepted_non_exact"] += non_exact
        by[ax]["normalization_attempts"] += normalized
        why[ax].update(reasons)
    table = {}
    for ax in selected:
        n = len(scenes)
        table[ax] = {
            "n": n,
            **{k: by[ax][k] for k in (
                "verified_correct", "rejected", "verified_wrong", "verified_exact",
                "accepted_non_exact", "normalization_attempts",
            )},
            "agreement_rate": round(by[ax]["verified_correct"] / n, 3),
            "false_accept_rate": round(by[ax]["verified_wrong"] / n, 3),
            "top_rejection_reasons": dict(why[ax].most_common(3)),
        }
    return {
        "scenes": len(scenes),
        "dataset_manifest_sha256": source["manifest_sha256"],
        "sample_sha256": hashlib.sha256(canonical_json(sample)).hexdigest(),
        "generator_config_sha256": config_hash(load_config(generator_config)),
        "recovery_enabled": recover_small_distortions,
        "axes": table,
    }
