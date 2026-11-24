"""Task Factory: fresh verified panels + paired variants for the judge UI (worker subcommand).

Invoked by the Rust API with a fixed argument vector:
    python -m panelproof.cli factory --seed S --count N --out DIR
Writes images, public tasks, a private key file, validation traces, pair list, DEMO ONLY model attempts and a
SHA-256 manifest that the API re-checks before publishing anything.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .demo_adapter import mock_attempts_for_rows
from .export import VARIANT_TO_CONTRACT, contract_evidence
from .mutations import make_nuisance, make_semantic_flip
from .question_bridge import (
    answer_from_trace,
    answers_agree,
    build_questions,
    contract_scene,
    response_schema,
)
from .render import evidence_annotations, png_bytes, render_scene
from .rules import PUMP_RULE
from .rust_bridge import verify_scenes
from .scene import Scene, generate_scene, load_config
from .schemas import SCHEMA_VERSION, PrivateTask, PublicTask
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
        "".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n" for r in rows),
        encoding="utf-8",
        newline="\n",
    )


def run_factory(seed: str, count: int, out: Path, difficulty: str = "medium") -> dict[str, Any]:
    if not (1 <= count <= MAX_COUNT):
        raise ValueError(f"count must be 1..{MAX_COUNT}")
    if difficulty not in PROFILES:
        raise ValueError(f"difficulty must be one of {sorted(PROFILES)}")
    cfg = {**load_config(), **PROFILES[difficulty]}
    if out.is_symlink() or (out.exists() and (not out.is_dir() or any(out.iterdir()))):
        raise ValueError("factory output must be a new or empty directory")
    (out / "images").mkdir(parents=True)
    tasks: list[dict[str, Any]] = []
    contract: list[dict[str, Any]] = []
    keys: list[dict[str, Any]] = []
    traces: dict[str, dict[str, Any]] = {}
    scenes = {}
    pairs: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    skipped = 0
    rust_pp = os.environ.get("PANELPROOF_RUST_PP")

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
            PublicTask.model_validate(
                {
                    "schema_version": SCHEMA_VERSION,
                    "task_id": tid,
                    "image_path": img,
                    "question": q.text,
                    "public_rules": q.public_rules,
                    "response_schema": response_schema(q),
                }
            ).model_dump(mode="json")
        )
        ans = {k: v for k, v in q.answer.items() if k != "tolerance_milli"}
        contract.append(
            PrivateTask.model_validate(
                {
                    "schema_version": SCHEMA_VERSION,
                    "task_id": tid,
                    "base_scene_id": scene.scene_id,
                    "group_id": _hid(seed, scene.seed.rsplit(":", 2)[-2], "grp"),
                    "variant_kind": VARIANT_TO_CONTRACT[vk if vk != "base" else "base"],
                    "split": "dev",
                    "skill": q.contract_skill,
                    "difficulty": {"band": difficulty},
                    "answer": ans,
                    "tolerance_milli": q.answer.get("tolerance_milli") if ans["kind"] == "numeric" else None,
                    "evidence_regions": contract_evidence(evidence_annotations(scene), pump_id) or None,
                    "solver_version": f"pp-rules-{SCHEMA_VERSION}+{trace['verifier_version']}",
                    "image_sha256": _sha(png),
                    "validation_status": "accepted",
                }
            ).model_dump(mode="json")
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
                "generator_readings": {
                    gauge.role: {"unit": gauge.unit, "value_milli": gauge.value_milli}
                    for gauge in scene.pump(pump_id).gauges
                },
                "validation": {
                    "verifier_version": trace["verifier_version"],
                    "verdict": tp["verdict"],
                    "derived": tp["derived"],
                    "readings": {
                        r: {k: g[k] for k in ("unit", "reading_milli", "uncertainty_mkpa", "center", "radius")}
                        for r, g in tp["gauges"].items()
                    },
                },
            }
        )
        traces[scene.scene_id] = trace
        if rust_pp:
            scenes[scene.scene_id] = contract_scene(scene)
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
            pid = sem.pump_id
            originals = {q.kind: q.answer for q in build_questions(base) if q.pump_id == pid}
            mutations = {q.kind: q.answer for q in build_questions(sem.scene) if q.pump_id == pid}
            preferred = ("state", "consistency") if i % 2 == 0 else ("consistency", "state")
            kind = next(
                (
                    k for k in preferred
                    if k in originals and k in mutations and not answers_agree(originals[k], mutations[k])
                ),
                None,
            )
            if kind is None:
                skipped += 1
                continue
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
    if rust_pp:
        rust_rows = verify_scenes(
            (scene.model_dump(mode="json") for scene in scenes.values()),
            executable=rust_pp,
            required=True,
        )
        assert rust_rows is not None
        agreement = {
            (scene.base_scene_id, pump.id): {"id": pump.id, **asdict(PUMP_RULE.solve(pump))} == actual
            for scene, rust in zip(scenes.values(), rust_rows, strict=True)
            for pump, actual in zip(scene.equipment, rust["equipment"], strict=True)
        }
        for key in keys:
            key["validation"]["rust_rule_agrees"] = agreement[(key["scene_id"], key["pump_id"])]
    (out / "public").mkdir()
    (out / "private").mkdir()
    # Shared-contract bundle (imported by the Axum API) plus web-demo extras.
    _jsonl(out / "public" / "tasks.jsonl", sorted(tasks, key=lambda r: r["task_id"]))
    _jsonl(out / "private" / "tasks.jsonl", sorted(contract, key=lambda r: r["task_id"]))
    _jsonl(out / "private" / "keys.jsonl", keys)
    _jsonl(out / "private" / "validation.jsonl", [{"scene_id": k, "trace": v} for k, v in sorted(traces.items())])
    _jsonl(out / "public" / "pairs.jsonl", pairs)
    _jsonl(out / "public" / "model_attempts.jsonl", mock_attempts_for_rows(rows, traces))
    files = {
        str(p.relative_to(out)).replace("\\", "/"): _sha(p.read_bytes()) for p in sorted(out.rglob("*")) if p.is_file()
    }
    manifest = {"schema_version": "1.0.0", "seed": seed, "count": count, "difficulty": difficulty, "files": files}
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return {"tasks": len(tasks), "pairs": len(pairs), "skipped_candidates": skipped, "out": str(out)}
