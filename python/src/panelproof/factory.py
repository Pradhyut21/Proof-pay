"""Task Factory: fresh verified panels + paired variants for the judge UI (worker subcommand).

Invoked by the Rust API with a fixed argument vector:
    python -m panelproof.cli factory --seed S --count N --out DIR
Writes images, public tasks, a private key file, validation traces, pair list, DEMO ONLY model attempts and a
SHA-256 manifest that the API re-checks before publishing anything.
"""

from __future__ import annotations

import hashlib
import json
import random
import shutil
from pathlib import Path
from typing import Any

from .demo_adapter import mock_attempts_for_rows
from .interim_questions import answer_from_trace, answers_agree, build_questions, response_schema
from .interim_rules import public_rules_text
from .mutations import make_nuisance, make_semantic_flip
from .render import evidence_annotations, png_bytes, render_scene
from .scene import Scene, generate_scene, load_config
from .validate import compare_trace_to_scene
from .verify import verify_png

MAX_COUNT = 50
PROFILES: dict[str, dict[str, Any]] = {
    "easy": {"pumps": {"min": 1, "max": 1}, "unit_weights": {"kPa": 1.0, "bar": 0.0, "psi": 0.0}},
    "medium": {"pumps": {"min": 1, "max": 1}},
    "hard": {"pumps": {"min": 2, "max": 2}},
}


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _hid(*parts: str, n: int = 16) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:n]


def _verified(scene: Scene) -> tuple[bytes, dict[str, Any]] | None:
    png = png_bytes(render_scene(scene))
    trace = verify_png(png)
    if trace["status"] != "verified" or not compare_trace_to_scene(trace, scene)["agree"]:
        return None
    return png, trace


def _jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n" for r in rows), encoding="utf-8"
    )


def run_factory(seed: str, count: int, out: Path, difficulty: str = "medium") -> dict[str, Any]:
    if not (1 <= count <= MAX_COUNT):
        raise ValueError(f"count must be 1..{MAX_COUNT}")
    if difficulty not in PROFILES:
        raise ValueError(f"difficulty must be one of {sorted(PROFILES)}")
    cfg = {**load_config(), **PROFILES[difficulty]}
    if out.exists():
        shutil.rmtree(out)
    (out / "images").mkdir(parents=True)
    tasks: list[dict[str, Any]] = []
    keys: list[dict[str, Any]] = []
    traces: dict[str, dict[str, Any]] = {}
    pairs: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    skipped = 0

    def emit(
        scene: Scene, png: bytes, trace: dict[str, Any], pump_id: str, kind: str, vk: str, pair: str | None
    ) -> str:
        q = next(q for q in build_questions(scene) if q.kind == kind and q.pump_id == pump_id)
        derived = answer_from_trace(q, next(p for p in trace["pumps"] if p["pump_id"] == pump_id))
        assert derived is not None and answers_agree(q.answer, derived)
        img = "images/im_" + _sha(png)[:16] + ".png"
        (out / img).write_bytes(png)
        tid = "t_" + _hid(seed, scene.scene_id, kind, pump_id)
        tasks.append(
            {
                "schema_version": "1.0.0",
                "task_id": tid,
                "image": img,
                "question": q.text,
                "rules": public_rules_text(),
                "response_schema": response_schema(q),
                "set": "factory",
            }
        )
        tp = next(p for p in trace["pumps"] if p["pump_id"] == pump_id)
        keys.append(
            {
                "task_id": tid,
                "answer": q.answer,
                "skill": q.skill,
                "kind": q.kind,
                "pump_id": pump_id,
                "role": q.role,
                "target_unit": q.target_unit,
                "variant_kind": vk,
                "pair_id": pair,
                "scene_id": scene.scene_id,
                "evidence": [e for e in evidence_annotations(scene) if e["pump"] == pump_id],
                "validation": {
                    "verifier_version": trace["verifier_version"],
                    "verdict": tp["verdict"],
                    "derived": tp["derived"],
                    "readings": {
                        r: {k: g[k] for k in ("unit", "reading_milli", "uncertainty_mkpa")}
                        for r, g in tp["gauges"].items()
                    },
                },
            }
        )
        traces[scene.scene_id] = trace
        rows.append({**keys[-1]})
        return tid

    for i in range(count):
        done = False
        for attempt in range(12):
            base = generate_scene(f"factory:{seed}:{difficulty}:{i}:{attempt}", cfg)
            rng = random.Random(f"{seed}:{i}:{attempt}:v")
            vb = _verified(base)
            sem = make_semantic_flip(base, rng)
            vs = _verified(sem.scene) if sem else None
            if not (vb and sem and vs):
                skipped += 1
                continue
            nui = make_nuisance(base, rng)
            vn = _verified(nui.scene) if nui else None
            kind = "state" if i % 2 == 0 else "consistency"
            pid = sem.pump_id
            tb = emit(base, *vb, pid, kind, "base", None)
            ts = emit(sem.scene, *vs, pid, kind, "semantic", None)
            pairs.append({"pair_id": "p_" + _hid(seed, str(i), "sem"), "task_ids": [tb, ts]})
            if nui and vn:
                tn = emit(nui.scene, *vn, pid, kind, "nuisance", None)
                pairs.append({"pair_id": "p_" + _hid(seed, str(i), "nui"), "task_ids": [tb, tn]})
            done = True
            break
        if not done:
            raise RuntimeError(f"could not build a verified group for index {i}")
    _jsonl(out / "tasks.jsonl", tasks)
    _jsonl(out / "sample_keys.jsonl", keys)
    _jsonl(out / "sample_validation.jsonl", [{"scene_id": k, "trace": v} for k, v in sorted(traces.items())])
    _jsonl(out / "pairs.jsonl", pairs)
    _jsonl(out / "model_attempts.jsonl", mock_attempts_for_rows(rows, traces))
    files = {
        str(p.relative_to(out)).replace("\\", "/"): _sha(p.read_bytes()) for p in sorted(out.rglob("*")) if p.is_file()
    }
    manifest = {"schema_version": "1.0.0", "seed": seed, "count": count, "difficulty": difficulty, "files": files}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"tasks": len(tasks), "pairs": len(pairs), "skipped_candidates": skipped, "out": str(out)}
