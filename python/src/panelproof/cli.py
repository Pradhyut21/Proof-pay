"""panelproof command line.

panelproof generate --seed S --count N --out DIR [--config C] [--workers W] [--preview]
panelproof verify   --dataset DIR [--out FILE]
panelproof variants --dataset DIR
panelproof build-dataset --config configs/benchmark.yaml --out DIR [--holdout-seed-file FILE]
panelproof audit-dataset --dataset DIR [--rebuild-config CONFIG] [--holdout-seed-file FILE]
panelproof metrics --tasks DIR --attempts FILE --out DIR
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from .render import evidence_annotations, png_bytes, render_scene
from .scene import canonical_json, config_hash, generate_scene, load_config

MAX_WORKERS = 8
MAX_COUNT = 5000


def sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _gen_one(args: tuple[str, str | None]) -> dict:
    seed, cfg_path = args
    cfg = load_config(cfg_path)
    t0 = time.perf_counter()
    scene = generate_scene(seed, cfg)
    img = render_scene(scene)
    data = png_bytes(img)
    return {
        "seed": seed,
        "scene_id": scene.scene_id,
        "png": data,
        "scene": scene.to_dict(),
        "evidence": evidence_annotations(scene),
        "render_ms": round((time.perf_counter() - t0) * 1000, 1),
    }


def generate_dataset(
    seed: str, count: int, out: Path, cfg_path: str | None, workers: int, preview: bool = False
) -> dict:
    count = min(max(count, 1), MAX_COUNT)
    workers = min(max(workers, 1), MAX_WORKERS)
    out.mkdir(parents=True, exist_ok=True)
    (out / "images").mkdir(exist_ok=True)
    (out / "private").mkdir(exist_ok=True)
    jobs = [(f"{seed}:{i:05d}", cfg_path) for i in range(count)]
    if workers == 1:
        results = [_gen_one(j) for j in jobs]
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(_gen_one, jobs, chunksize=4))
    files: dict[str, str] = {}
    with (out / "private" / "scenes.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        for r in results:
            rel = f"images/{r['scene_id']}.png"
            (out / rel).write_bytes(r["png"])
            files[rel] = sha256_hex(r["png"])
            rec = {
                "scene_id": r["scene_id"],
                "seed": r["seed"],
                "scene": r["scene"],
                "evidence": r["evidence"],
                "png_sha256": files[rel],
            }
            fh.write(json.dumps(rec, sort_keys=True) + "\n")
    cfg = load_config(cfg_path)
    manifest = {
        "schema_version": "1.0.0",
        "base_seed": seed,
        "count": count,
        "generator_config_sha256": config_hash(cfg),
        "files": dict(sorted(files.items())),
        "render_ms": {
            "mean": round(sum(r["render_ms"] for r in results) / len(results), 1),
            "max": max(r["render_ms"] for r in results),
        },
    }
    manifest["manifest_sha256"] = sha256_hex(
        canonical_json({k: v for k, v in manifest.items() if k not in ("render_ms",)})
    )
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if preview:
        from PIL import Image

        ids = sorted(files)[:12]
        sheet = Image.new("RGB", (4 * 320, 3 * 240), (255, 255, 255))
        for k, rel in enumerate(ids):
            im = Image.open(out / rel).resize((320, 240))
            sheet.paste(im, ((k % 4) * 320, (k // 4) * 240))
        sheet.save(out / "preview.png")
    return manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="panelproof")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate", help="render base scenes")
    g.add_argument("--seed", default="pilot")
    g.add_argument("--count", type=int, default=20)
    g.add_argument("--out", required=True)
    g.add_argument("--config", default=None)
    g.add_argument("--workers", type=int, default=1)
    g.add_argument("--preview", action="store_true")
    v = sub.add_parser("verify", help="independent raster verification of a generated directory")
    v.add_argument("--dataset", required=True)
    v.add_argument("--out", default=None)
    pt = sub.add_parser("perturb", help="verifier agreement under moderate perturbations")
    pt.add_argument("--dataset", required=True)
    pt.add_argument("--limit", type=int, default=60)
    pt.add_argument("--workers", type=int, default=4)
    pt.add_argument("--out", default=None)
    da = sub.add_parser("demo-attempts", help="offline mock attempts (DEMO ONLY)")
    da.add_argument("--dataset", required=True)
    da.add_argument("--out", required=True)
    da.add_argument("--split", default=None)
    fa = sub.add_parser("factory", help="fresh verified panels with paired variants (used by the API)")
    fa.add_argument("--seed", required=True)
    fa.add_argument("--count", type=int, required=True)
    fa.add_argument("--out", required=True)
    fa.add_argument("--difficulty", default="medium", choices=["easy", "medium", "hard"])
    for name in ("build-dataset", "audit-dataset", "metrics", "variants"):
        sub.add_parser(name, add_help=False)
    args, rest = ap.parse_known_args(argv)

    if args.cmd == "generate":
        m = generate_dataset(args.seed, args.count, Path(args.out), args.config, args.workers, args.preview)
        print(json.dumps({"count": m["count"], "manifest_sha256": m["manifest_sha256"], "render_ms": m["render_ms"]}))
        return 0
    if args.cmd == "verify":
        from .validate import verify_dataset_dir

        summary = verify_dataset_dir(Path(args.dataset), Path(args.out) if args.out else None)
        print(json.dumps(summary, indent=2))
        return 0
    if args.cmd == "demo-attempts":
        from .demo_adapter import generate_demo_attempts, write_attempts

        rows = generate_demo_attempts(Path(args.dataset), args.split)
        write_attempts(Path(args.out), rows)
        print(json.dumps({"attempts": len(rows), "label": "DEMO ONLY", "out": args.out}))
        return 0
    if args.cmd == "factory":
        from .factory import run_factory

        print(json.dumps(run_factory(args.seed, args.count, Path(args.out), args.difficulty)))
        return 0
    if args.cmd == "perturb":
        from .perturb import run_perturbations

        res = run_perturbations(Path(args.dataset), args.limit, min(args.workers, MAX_WORKERS))
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(json.dumps(res, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(res, indent=2))
        return 0
    if args.cmd == "build-dataset":
        from .export import main_build

        return main_build(rest)
    if args.cmd == "audit-dataset":
        from .export import main_audit

        return main_audit(rest)
    if args.cmd == "metrics":
        from .metrics import main_metrics

        return main_metrics(rest)
    if args.cmd == "variants":
        from .mutations import main_variants

        return main_variants(rest)
    return 2


if __name__ == "__main__":
    sys.exit(main())
