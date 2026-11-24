"""Build, validate, split, hash and export the PanelProof dataset (PP-11).

Public artifacts (images, tasks JSONL) never contain seeds, answers or scene truth; those live in
`private/` and are only committed to by SHA-256 in the manifest.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
import shutil
import stat
from collections import Counter, defaultdict
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor
from contextlib import nullcontext
from functools import cache
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory, mkdtemp
from typing import Any

import cv2
import numpy as np
import yaml

from .mutations import Variant, make_missing, make_nuisance, make_preserving, make_semantic_flip
from .question_bridge import (
    Question,
    answer_from_trace,
    answers_agree,
    build_questions,
    response_schema,
)
from .render import check_layout, evidence_annotations, png_bytes, render_scene
from .scene import Scene, canonical_json, config_hash, generate_scene, load_config, scene_from_dict
from .schemas import SCHEMA_VERSION, PrivateTask, PublicTask
from .units import repo_root
from .validate import compare_trace_to_scene
from .verify import VERIFIER_VERSION, verify_png

PUBLIC_KEYS = {"schema_version", "task_id", "image_path", "question", "public_rules", "response_schema"}
SPLIT_TO_CONTRACT = {"dev": "dev", "frozen_main": "test_frozen", "frozen_heldout_style": "test_frozen"}
X_SELECTION_PATH = "public/x_balanced_selection.json"
X_CELL_NAMES = (
    "expected_off_observed_off",
    "expected_off_observed_on",
    "expected_on_observed_off",
    "expected_on_observed_on",
)
VARIANT_TO_CONTRACT = {
    "base": "original",
    "semantic": "semantic",
    "preserving": "semantic_preserve",
    "nuisance": "nonsemantic",
    "missing": "evidence_removed",
}
OWNER_FILE = ".panelproof-dataset.json"
OWNER_FORMAT = "panelproof.dataset.1"


def contract_evidence(evidence: list[dict[str, Any]], pump_id: str) -> list[dict[str, Any]]:
    """Generator-side boxes as contract EvidenceRegion records (instrument ids are pump + part)."""
    out = []
    for e in evidence:
        if e["pump"] != pump_id or e["kind"] == "module":
            continue
        x0, y0, x1, y1 = (max(0, int(round(v))) for v in e["box"])
        out.append(
            {
                "instrument_id": f"{e['pump']}_{e['kind']}".replace("-", "_"),
                "x": x0,
                "y": y0,
                "width": max(1, x1 - x0),
                "height": max(1, y1 - y0),
            }
        )
    return out


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def hid(*parts: str, n: int = 16) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:n]


def jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n")


def dhash(png: bytes) -> int:
    g = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)
    s = cv2.resize(g, (9, 8), interpolation=cv2.INTER_AREA)
    bits = (s[:, 1:] > s[:, :-1]).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)


def difficulty(scene: Scene, pump_id: str) -> str:
    """easy / medium / hard from visible complexity: pumps, mixed or psi units, thin threshold margin."""
    p = scene.pump(pump_id)
    gi, go = p.gauge("INLET"), p.gauge("OUTLET")
    score = (len(scene.pumps) > 1) + (gi.unit != go.unit) + ("psi" in (gi.unit, go.unit))
    score += abs(p.delta_mkpa() - 300_000) < 3 * (gi.minor_mkpa + go.minor_mkpa)
    return "easy" if score <= 1 else ("medium" if score == 2 else "hard")


def _work(scene_d: dict[str, Any]) -> dict[str, Any]:
    scene = scene_from_dict(scene_d)
    png = png_bytes(render_scene(scene))
    trace = verify_png(png)
    return {
        "png": png,
        "trace": trace,
        "layout_errors": check_layout(scene),
        "agree": compare_trace_to_scene(trace, scene),
        "evidence": evidence_annotations(scene),
    }


def _run(pool: ProcessPoolExecutor | None, scenes: list[Scene]) -> list[dict[str, Any]]:
    ds = [s.to_dict() for s in scenes]
    return list(pool.map(_work, ds, chunksize=2)) if pool else [_work(d) for d in ds]


# ------------------------------------------------------------------ build


def _in_checkout(path: Path) -> bool:
    return path.is_relative_to(repo_root().resolve()) or any(
        (parent / ".git").exists() for parent in (path, *path.parents)
    )


def _holdout_seed(path: Path) -> str:
    source = path.expanduser().absolute()
    resolved = source.resolve(strict=True)
    if _in_checkout(source) or _in_checkout(resolved) or not resolved.is_file():
        raise ValueError("holdout seed must be a regular file outside all Git checkouts")
    with resolved.open("rb") as seed_file:
        raw = seed_file.read(128)
    value = raw.strip()
    if len(raw) == 128 or not re.fullmatch(rb"[0-9a-fA-F]{64}", value):
        raise ValueError("holdout seed file must contain exactly 64 random hexadecimal characters")
    return value.decode("ascii").lower()


def _is_link(path: Path) -> bool:
    attrs = getattr(path.lstat(), "st_file_attributes", 0)
    return path.is_symlink() or bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _inventory(directory: Path) -> list[str]:
    paths = []
    for path in directory.rglob("*"):
        if _is_link(path) or not (path.is_file() or path.is_dir()):
            raise ValueError("dataset directory contains a link or unsupported file type")
        relative = path.relative_to(directory).as_posix()
        if relative != OWNER_FILE:
            paths.append(relative)
    return sorted(paths)


def _check_destination(directory: Path) -> None:
    if not directory.exists() and not directory.is_symlink():
        return
    if _is_link(directory) or not directory.is_dir():
        raise ValueError("dataset output must be a directory without links")
    if not any(directory.iterdir()):
        return
    marker = directory / OWNER_FILE
    if not marker.is_file() or _is_link(marker):
        raise ValueError("dataset output is not empty or owned by PanelProof; use a new directory")
    owner = json.loads(marker.read_text(encoding="utf-8"))
    if owner != {"format": OWNER_FORMAT, "paths": _inventory(directory)}:
        raise ValueError("dataset output contains unowned or missing artifacts; use a new directory")


def _publish_dataset(staged: Path, destination: Path, previous: Path) -> None:
    _check_destination(destination)
    if destination.exists():
        destination.rename(previous)
    try:
        _check_destination(previous)
        staged.rename(destination)
    except BaseException:
        if previous.exists():
            try:
                previous.rename(destination)
            except OSError as error:
                raise RuntimeError(f"dataset was preserved for recovery at {previous}") from error
        raise


def build_dataset(
    cfg_path: Path, out: Path, workers: int | None = None, *, holdout_seed_file: Path | None = None
) -> dict[str, Any]:
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    gcfg = load_config(repo_root() / cfg["generator_config"])
    workers = workers if workers is not None else cfg["workers"]
    if workers < 1:
        raise ValueError("workers must be positive")

    destination = out.expanduser().absolute()
    _check_destination(destination)
    destination = destination.resolve()
    if holdout_seed_file is None:
        seed = cfg.get("repro_seed", cfg.get("base_seed"))
        if not isinstance(seed, str) or not seed:
            raise ValueError("benchmark configuration must provide a public reproducibility seed")
        metadata = {"dataset_purpose": "repro"}
    else:
        if _in_checkout(destination):
            raise ValueError("measured holdout output must be outside all Git checkouts")
        seed = _holdout_seed(holdout_seed_file)
        metadata = {"dataset_purpose": "measured_holdout", "seed_commitment_sha256": sha(seed.encode("ascii"))}

    destination.parent.mkdir(parents=True, exist_ok=True)
    scratch = Path(mkdtemp(prefix=".panelproof-stage-", dir=destination.parent))
    staged = scratch / "bundle"
    previous = scratch / "previous"
    installed = False
    try:
        staged.mkdir()
        report = _build_dataset(cfg, gcfg, staged, workers, seed, metadata)
        audit = audit_dataset(staged)
        if not audit["pass"]:
            raise ValueError("staged dataset failed its artifact and split audit")
        owner = {"format": OWNER_FORMAT, "paths": _inventory(staged)}
        (staged / OWNER_FILE).write_text(json.dumps(owner) + "\n", encoding="utf-8")
        _publish_dataset(staged, destination, previous)
        installed = True
        return report
    finally:
        if installed or not previous.exists():
            shutil.rmtree(scratch, ignore_errors=True)


def _build_dataset(
    cfg: dict[str, Any],
    gcfg: dict[str, Any],
    out: Path,
    workers: int,
    generation_seed: str,
    metadata: dict[str, str],
) -> dict[str, Any]:
    executor = ProcessPoolExecutor(max_workers=workers) if workers > 1 else nullcontext()
    with executor as pool:
        return _generate_dataset(cfg, gcfg, out, pool, generation_seed, metadata)


def _generate_dataset(
    cfg: dict[str, Any],
    gcfg: dict[str, Any],
    out: Path,
    pool: ProcessPoolExecutor | None,
    generation_seed: str,
    metadata: dict[str, str],
) -> dict[str, Any]:
    ledger: list[dict[str, Any]] = []
    attempts = 0
    base_attempts = 0

    # 1. base scenes: generate -> render -> independent verification -> accept/reject
    accepted: list[dict[str, Any]] = []
    i = 0
    while len(accepted) < cfg["base_groups"] and i < cfg["max_attempts"]:
        batch = [
            generate_scene(f"{generation_seed}:{j:05d}", gcfg) for j in range(i, min(i + 24, cfg["max_attempts"]))
        ]
        for sc, res in zip(batch, _run(pool, batch), strict=True):
            attempts += 1
            base_attempts += 1
            why = list(res["layout_errors"])
            if res["trace"]["status"] != "verified":
                why += sorted({r for p in res["trace"]["pumps"] for r in p["reasons"]})
            elif not res["agree"]["agree"]:
                why.append("verifier_truth_disagreement")
            if why or len(accepted) >= cfg["base_groups"]:
                if why:
                    ledger.append({"stage": "base", "scene_ref": hid(sc.seed), "reasons": why})
                continue
            accepted.append({"scene": sc, "res": res, "group_id": "g_" + hid(sc.seed, "group", n=12)})
        i += len(batch)

    # 2. variants per group
    var_specs: list[tuple[dict[str, Any], Variant]] = []
    var_cfg = cfg["variants"]
    for idx, g in enumerate(accepted):
        rng = random.Random(f"{g['scene'].seed}:var")
        makers = [make_semantic_flip]
        if idx % var_cfg["nuisance_every"] == 0:
            makers.append(make_nuisance)
        if idx % var_cfg["preserving_every"] == 1:
            makers.append(make_preserving)
        makers.append(make_missing)
        for fn in makers:
            v = None
            for _try in range(6):
                v = fn(g["scene"], rng, tag=f"{fn.__name__}{_try}")
                if v:
                    break
            if v is None:
                ledger.append(
                    {"stage": "variant", "scene_ref": g["group_id"], "reasons": [f"{fn.__name__}:no_valid_edit"]}
                )
                continue
            var_specs.append((g, v))
    diag_seen = 0
    kept: list[tuple[dict[str, Any], Variant]] = []
    for g, v in var_specs:
        if v.kind == "missing":
            if diag_seen >= var_cfg["diagnostic_target"]:
                continue
            diag_seen += 1
        kept.append((g, v))
    results = _run(pool, [v.scene for _, v in kept])
    variants: list[dict[str, Any]] = []
    for (g, v), res in zip(kept, results, strict=True):
        attempts += 1
        if v.kind == "missing":
            reasons = {r for p in res["trace"]["pumps"] for r in p["reasons"]}
            covered_role = v.edit.split(":")[1]
            ok = res["trace"]["status"] != "verified" and any(
                r.startswith(covered_role + ":") or covered_role in r for r in reasons
            )
            if not ok:
                ledger.append(
                    {
                        "stage": "diagnostic",
                        "scene_ref": g["group_id"],
                        "reasons": ["verifier_did_not_flag_missing_evidence"],
                    }
                )
                continue
        else:
            if res["trace"]["status"] != "verified" or not res["agree"]["agree"] or res["layout_errors"]:
                ledger.append(
                    {
                        "stage": f"variant:{v.kind}",
                        "scene_ref": g["group_id"],
                        "reasons": sorted({r for p in res["trace"]["pumps"] for r in p["reasons"]})
                        or ["verifier_disagreement"],
                    }
                )
                continue
        variants.append({"group": g, "variant": v, "res": res})

    # 3. split units: group + near-duplicate clustering, then deterministic split
    units = _split_units(accepted, cfg)
    split_of: dict[str, str] = units["split_of_group"]

    # 4. tasks
    tasks = _select_tasks(accepted, variants, cfg, split_of)
    public_dir = out / "public"
    images: dict[str, str] = {}

    def image_path(png: bytes) -> str:
        key = "im_" + sha(png)[:16]
        rel = f"images/{key}.png"
        if rel not in images:
            (out / rel).parent.mkdir(parents=True, exist_ok=True)
            (out / rel).write_bytes(png)
            images[rel] = sha(png)
        return rel

    pub: dict[str, list[dict[str, Any]]] = defaultdict(list)
    priv: list[dict[str, Any]] = []
    contract_rows: list[dict[str, Any]] = []
    for t in tasks:
        rel = image_path(t["png"])
        q: Question = t["q"]
        diag = t["set"] == "diagnostic"
        task_id = "t_" + hid(
            cfg["dataset_version"], t["scene"].scene_id, q.kind, q.pump_id, q.role or "", q.target_unit or ""
        )
        public = {
            "schema_version": SCHEMA_VERSION,
            "task_id": task_id,
            "image_path": rel,
            "question": q.text,
            "public_rules": q.public_rules,
            "response_schema": response_schema(q, diag),
        }
        assert set(public) == PUBLIC_KEYS
        PublicTask.model_validate(public)
        bucket = "diagnostic" if diag else ("dev" if t["split"] == "dev" else "frozen")
        pub[bucket].append(public)
        ans = {"kind": "category", "value": "INSUFFICIENT"} if diag else {
            k: v for k, v in q.answer.items() if k != "tolerance_milli"
        }
        contract_priv = PrivateTask.model_validate(
            {
                "schema_version": SCHEMA_VERSION,
                "task_id": task_id,
                "base_scene_id": t["scene"].scene_id,
                "group_id": hid(t["group_id"], "grp"),
                "variant_kind": VARIANT_TO_CONTRACT[t["variant_kind"]],
                "split": "diagnostic_abstain" if diag else SPLIT_TO_CONTRACT[t["split"]],
                "skill": q.contract_skill,
                "difficulty": {"band": difficulty(t["scene"], q.pump_id)},
                "answer": ans,
                "tolerance_milli": None if diag or ans["kind"] != "numeric" else q.answer["tolerance_milli"],
                "evidence_regions": contract_evidence(t["evidence"], q.pump_id) or None,
                "solver_version": f"pp-rules-{SCHEMA_VERSION}+{VERIFIER_VERSION}",
                "image_sha256": images[rel],
                "validation_status": "accepted",
            }
        )
        contract_rows.append(contract_priv.model_dump(mode="json"))
        priv.append(
            {
                "task_id": task_id,
                "set": t["set"],
                "split": t["split"],
                "skill": q.skill,
                "kind": q.kind,
                "pump_id": q.pump_id,
                "role": q.role,
                "target_unit": q.target_unit,
                "difficulty": difficulty(t["scene"], q.pump_id),
                "answer": q.answer if not diag else {"kind": "category", "value": "INSUFFICIENT"},
                "group_id": t["group_id"],
                "pair_id": t.get("pair_id"),
                "pair_ids": t.get("pair_ids", []),
                "variant_kind": t["variant_kind"],
                "variant_edit": t.get("edit"),
                "layout_family": t["scene"].layout_family(),
                "theme": t["scene"].theme,
                "seed": t["scene"].seed,
                "scene_id": t["scene"].scene_id,
                "image": rel,
                "alarm_on": t["scene"].pump(q.pump_id).alarm,
                "run_on": t["scene"].pump(q.pump_id).run,
                "evidence": [e for e in t["evidence"] if e["pump"] == q.pump_id],
                "verifier_version": VERIFIER_VERSION,
                "verifier_status": t["trace"]["status"],
                "diff": t.get("diff", []),
            }
        )
    for k in pub:
        pub[k].sort(key=lambda r: r["task_id"])
        jsonl(public_dir / f"{k}.jsonl", pub[k])
    # Shared-contract bundle layout (what the Axum API imports): public/tasks.jsonl + private/tasks.jsonl.
    jsonl(public_dir / "tasks.jsonl", sorted((r for rows in pub.values() for r in rows), key=lambda r: r["task_id"]))
    jsonl(out / "private" / "tasks.jsonl", sorted(contract_rows, key=lambda r: r["task_id"]))
    priv.sort(key=lambda r: r["task_id"])
    jsonl(out / "private" / "answers.jsonl", priv)
    jsonl(
        out / "private" / "validation.jsonl",
        sorted(
            [
                {"scene_id": t["scene"].scene_id, "trace": t["trace"], "agreement": t["agree"]["agree"]}
                for t in {t["scene"].scene_id: t for t in tasks}.values()
            ],
            key=lambda r: r["scene_id"],
        ),
    )
    jsonl(out / "private" / "rejections.jsonl", ledger)
    (out / "private" / "splits.json").write_text(
        json.dumps(units["report"], indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    x_selection = select_balanced_x(priv)
    (out / X_SELECTION_PATH).write_text(
        json.dumps(x_selection, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest = _manifest(out, cfg, gcfg, metadata)
    report = _report(cfg, (attempts, base_attempts), accepted, variants, tasks, ledger, units, manifest)
    report["x_balanced_selection"] = _x_selection_summary(x_selection)
    (out / "dataset_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_samples(out, cfg, priv, pub)
    return report


def semantic_key(scene: Scene) -> str:
    """Appearance-free content key: two scenes with the same key are near-duplicates (same tasks)."""
    sig = [
        (p.pump_id, p.run, p.alarm, sorted((g.role, g.unit, g.min_milli, g.max_milli, g.value_milli) for g in p.gauges))
        for p in scene.pumps
    ]
    return hashlib.sha256(canonical_json(sig)).hexdigest()


def _x_cell(row: dict[str, Any]) -> int:
    observed = row["alarm_on"]
    answer = row["answer"]["value"]
    if type(observed) is not bool or answer not in {"CONSISTENT", "CONTRADICTION"}:
        raise ValueError("X task is missing its binary alarm and consistency categories")
    expected = observed if answer == "CONSISTENT" else not observed
    return 2 * expected + observed


def _x_components(
    rows: list[dict[str, Any]],
) -> tuple[dict[str, list[list[dict[str, Any]]]], dict[str, list[str]]]:
    by_id = {row["task_id"]: row for row in rows}
    if len(by_id) != len(rows):
        raise ValueError("duplicate X task ID")
    parents = {task_id: task_id for task_id in by_id}
    pairs: dict[str, list[str]] = defaultdict(list)

    def find(task_id: str) -> str:
        while parents[task_id] != task_id:
            parents[task_id] = parents[parents[task_id]]
            task_id = parents[task_id]
        return task_id

    for task_id, row in by_id.items():
        for pair_id in row.get("pair_ids") or ([row["pair_id"]] if row.get("pair_id") else []):
            pairs[pair_id].append(task_id)
    for members in pairs.values():
        if len(set(members)) != 2 or len(members) != 2:
            raise ValueError("X pair must have exactly two distinct members")
        left, right = members
        if by_id[left]["split"] != by_id[right]["split"]:
            raise ValueError("X pair crosses dataset splits")
        parents[find(left)] = find(right)

    linked: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for task_id, row in by_id.items():
        if row["split"] not in SPLIT_TO_CONTRACT:
            raise ValueError("X task has an unknown dataset split")
        linked[find(task_id)].append(row)

    by_split: dict[str, list[list[dict[str, Any]]]] = defaultdict(list)
    for component in linked.values():
        by_split[component[0]["split"]].append(component)
    return by_split, pairs


def _x_counts(rows: Iterable[dict[str, Any]]) -> tuple[int, ...]:
    counts = Counter(_x_cell(row) for row in rows)
    return tuple(counts[index] for index in range(len(X_CELL_NAMES)))


def _largest_balanced_x_components(
    components: list[list[dict[str, Any]]], target: int
) -> list[list[dict[str, Any]]]:
    """Find the largest equal-cell cohort by packing whole pair components."""
    by_shape: dict[tuple[int, ...], list[list[dict[str, Any]]]] = defaultdict(list)
    for component in components:
        shape = _x_counts(component)
        if all(count <= target for count in shape):
            by_shape[shape].append(component)
    # Components with the same shape are interchangeable for balance. Larger shapes constrain
    # the answer first, leaving single-cell components available to fill any gaps.
    shapes = sorted(by_shape, key=lambda shape: (-sum(shape), shape))
    availability = [(0,) * len(X_CELL_NAMES)] * (len(shapes) + 1)
    for index in range(len(shapes) - 1, -1, -1):
        shape = shapes[index]
        availability[index] = tuple(
            after + count * len(by_shape[shape])
            for after, count in zip(availability[index + 1], shape, strict=True)
        )

    @cache
    def solve(index: int, remaining: tuple[int, ...]) -> tuple[int, ...] | None:
        if index == len(shapes):
            return () if not any(remaining) else None
        if any(need > have for need, have in zip(remaining, availability[index], strict=True)):
            return None
        shape = shapes[index]
        active_cells = [
            (need, count, after)
            for need, count, after in zip(remaining, shape, availability[index + 1], strict=True)
            if count
        ]
        maximum = min(len(by_shape[shape]), min(need // count for need, count, _ in active_cells))
        minimum = max(
            0, max((need - after + count - 1) // count for need, count, after in active_cells)
        )
        for quantity in range(maximum, minimum - 1, -1):
            rest = tuple(need - quantity * count for need, count in zip(remaining, shape, strict=True))
            suffix = solve(index + 1, rest)
            if suffix is not None:
                return (quantity, *suffix)
        return None

    for per_cell in range(target, 0, -1):
        quantities = solve(0, (per_cell,) * len(X_CELL_NAMES))
        if quantities is not None:
            return [
                component
                for shape, quantity in zip(shapes, quantities, strict=True)
                for component in by_shape[shape][:quantity]
            ]
    return []


def _x_cue_shift(counts: tuple[int, ...]) -> float | None:
    off_off, off_on, on_off, on_on = counts
    observed_off, observed_on = off_off + on_off, off_on + on_on
    if not observed_off or not observed_on:
        return None
    return round(100 * abs(off_off / observed_off - on_on / observed_on), 3)


def select_balanced_x(private_tasks: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Select complete X pair components with equally populated expected/observed lamp cells."""
    rows = sorted(
        (row for row in private_tasks if row["set"] == "main" and row["kind"] == "consistency"),
        key=lambda row: row["task_id"],
    )
    by_split, original_pairs = _x_components(rows)
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "selector": "x-four-cell-pairs-v1",
        "splits": {},
    }
    for split in SPLIT_TO_CONTRACT:
        components = by_split[split]
        before = _x_counts(row for component in components for row in component)
        selected = _largest_balanced_x_components(components, min(before))
        selected_rows = [row for component in selected for row in component]
        after = _x_counts(selected_rows)
        task_ids = sorted(row["task_id"] for row in selected_rows)
        task_id_set = set(task_ids)
        status = "balanced"
        if not task_ids:
            status = "infeasible_with_pairs" if min(before) else "missing_cell"
        result["splits"][split] = {
            "status": status,
            "task_ids": task_ids,
            "task_ids_sha256": sha(canonical_json(task_ids)),
            "eligible_count": sum(before),
            "selected_count": len(task_ids),
            "eligible_cell_counts": dict(zip(X_CELL_NAMES, before, strict=True)),
            "selected_cell_counts": dict(zip(X_CELL_NAMES, after, strict=True)),
            "eligible_max_cue_shift_pp": _x_cue_shift(before),
            "selected_max_cue_shift_pp": _x_cue_shift(after),
            "selected_component_count": len(selected),
            "selected_pair_count": sum(
                all(member in task_id_set for member in pair) for pair in original_pairs.values()
            ),
        }
    return result


def _x_selection_summary(selection: dict[str, Any]) -> dict[str, Any]:
    return {
        split: {key: value for key, value in cohort.items() if key != "task_ids"}
        for split, cohort in selection["splits"].items()
    }


def _split_units(accepted: list[dict[str, Any]], cfg: dict[str, Any]) -> dict[str, Any]:
    keys = [semantic_key(a["scene"]) for a in accepted]
    hs = [dhash(a["res"]["png"]) for a in accepted]
    parent = list(range(len(accepted)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    merged_pairs = 0
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            if keys[i] == keys[j] or hs[i] == hs[j] and accepted[i]["res"]["png"] == accepted[j]["res"]["png"]:
                parent[find(i)] = find(j)
                merged_pairs += 1
    unit_of = {
        accepted[i]["group_id"]: "u_" + hid(str(find(i)), accepted[find(i)]["group_id"], n=10)
        for i in range(len(accepted))
    }
    unit_theme: dict[str, bool] = defaultdict(bool)
    for a in accepted:
        unit_theme[unit_of[a["group_id"]]] |= a["scene"].theme == cfg["heldout_theme"]
    units = sorted(set(unit_of.values()), key=lambda u: hid(u, "split"))
    movable = [u for u in units if not unit_theme[u]]
    n_dev_groups = round(cfg["dev_fraction"] * len(accepted))
    dev_units: set[str] = set()
    count = 0
    for u in movable:
        if count >= n_dev_groups:
            break
        dev_units.add(u)
        count += sum(1 for g, uu in unit_of.items() if uu == u)
    split_of = {}
    for a in accepted:
        u = unit_of[a["group_id"]]
        split_of[a["group_id"]] = (
            "dev" if u in dev_units else ("frozen_heldout_style" if unit_theme[u] else "frozen_main")
        )
    return {
        "split_of_group": split_of,
        "unit_of": unit_of,
        "report": {
            "groups": len(accepted),
            "split_units": len(set(unit_of.values())),
            "near_duplicate_pairs_merged": merged_pairs,
            "counts": dict(Counter(split_of.values())),
        },
    }


def _task(
    g: dict[str, Any], scene: Scene, res: dict[str, Any], q: Question, split: str, **kw: Any
) -> dict[str, Any] | None:
    tp = next((p for p in res["trace"]["pumps"] if p.get("pump_id") == q.pump_id), None)
    if tp is None or tp["verdict"] != "verified":
        return None
    derived = answer_from_trace(q, tp)
    if derived is None or not answers_agree(q.answer, derived):
        return None  # independently derived answer disagrees with the reference: reject the task
    return {
        "scene": scene,
        "png": res["png"],
        "trace": res["trace"],
        "evidence": res["evidence"],
        "q": q,
        "agree": res["agree"],
        "split": split,
        "group_id": g["group_id"],
        "set": "main",
        **kw,
    }


def _select_tasks(
    accepted: list[dict[str, Any]], variants: list[dict[str, Any]], cfg: dict[str, Any], split_of: dict[str, str]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: dict[tuple[str, str, str, str], dict[str, Any]] = {}

    def add(t: dict[str, Any] | None) -> None:
        if not t:
            return
        q = t["q"]
        key = (t["scene"].scene_id, q.kind, q.pump_id, (q.role or "") + (q.target_unit or ""))
        previous = seen.get(key)
        pair = t.get("pair_id")
        if previous is not None:
            if pair:
                previous.setdefault("pair_id", pair)
                previous.setdefault("pair_ids", []).append(pair)
            return
        if pair:
            t["pair_ids"] = [pair]
        seen[key] = t
        out.append(t)

    def pick(scene: Scene, kind: str, pump: str, role: str | None = None) -> Question | None:
        return next(
            (
                q
                for q in build_questions(scene)
                if q.kind == kind and q.pump_id == pump and (role is None or q.role == role)
            ),
            None,
        )

    for v in variants:
        g, var, res = v["group"], v["variant"], v["res"]
        gid, split = g["group_id"], split_of[g["group_id"]]
        base, bres = g["scene"], g["res"]
        if var.kind == "missing":
            q = pick(var.scene, "state", var.pump_id)
            out.append(
                {
                    "scene": var.scene,
                    "png": res["png"],
                    "trace": res["trace"],
                    "evidence": res["evidence"],
                    "q": q,
                    "agree": res["agree"],
                    "split": split,
                    "group_id": gid,
                    "set": "diagnostic",
                    "variant_kind": "missing",
                    "edit": var.edit,
                    "diff": var.diff,
                }
            )
            continue
        kinds = {
            "semantic": [("state", None), ("consistency", None)],
            "nuisance": [("state", None), ("consistency", None)],
            "preserving": [("state", None), ("delta", None)],
        }[var.kind]
        pump = var.pump_id or base.pumps[0].pump_id
        for kind, role in kinds:
            before = pick(base, kind, pump, role)
            after = pick(var.scene, kind, pump, role)
            if before is None or after is None:
                continue
            changes_answer = not answers_agree(before.answer, after.answer)
            if changes_answer != (var.kind == "semantic"):
                continue
            pid = "p_" + hid(gid, var.kind, var.edit, kind, pump, role or "")
            original = _task(g, base, bres, before, split, pair_id=pid, variant_kind="base")
            changed = _task(
                g, var.scene, res, after, split, pair_id=pid, variant_kind=var.kind,
                edit=var.edit, diff=var.diff,
            )
            if original is not None and changed is not None:
                add(original)
                add(changed)

    # fill per-skill minimums from base scenes, in deterministic hash order
    def count(skill: str) -> int:
        return sum(1 for t in out if t["set"] == "main" and t["q"].skill == skill)

    pool = sorted(
        ((a, p) for a in accepted for p in a["scene"].pumps),
        key=lambda ap: hid(ap[0]["group_id"], ap[1].pump_id, "fill"),
    )
    plan = [("R", "read"), ("C", "convert"), ("M", "state"), ("M", "delta"), ("X", "consistency")]
    for skill, kind in plan:
        for a, p in pool:
            if count(skill) >= cfg["targets"][skill]:
                break
            roles = ["OUTLET"] if kind == "convert" else ["INLET", "OUTLET"] if kind == "read" else [None]
            role = roles[int(hid(a["group_id"], p.pump_id, kind, n=4), 16) % len(roles)]
            q = pick(a["scene"], kind, p.pump_id, role)
            if q:
                add(_task(a, a["scene"], a["res"], q, split_of[a["group_id"]], variant_kind="base"))
    for t in out:
        t.setdefault("variant_kind", "base")
    return out


def _manifest(
    out: Path, cfg: dict[str, Any], gcfg: dict[str, Any], metadata: dict[str, str]
) -> dict[str, Any]:
    files = {
        str(p.relative_to(out)).replace("\\", "/"): sha(p.read_bytes())
        for p in sorted(out.rglob("*"))
        if p.is_file() and p.name not in ("manifest.json", "dataset_report.json")
    }
    public = {k: v for k, v in files.items() if not k.startswith("private/") and not k.startswith("samples/")}
    commitments = {k: v for k, v in files.items() if k.startswith("private/")}
    body = {
        **metadata,
        "schema_version": SCHEMA_VERSION,
        "dataset_version": cfg["dataset_version"],
        "verifier_version": VERIFIER_VERSION,
        "generator_config_sha256": config_hash(gcfg),
        "benchmark_config_sha256": config_hash(cfg),
        "public_files": public,
        "private_commitments": commitments,
    }
    body["manifest_sha256"] = sha(canonical_json(body))
    (out / "manifest.json").write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return body


def _report(cfg, att, accepted, variants, tasks, ledger, units, manifest) -> dict[str, Any]:
    attempts, base_attempts = att
    main = [t for t in tasks if t["set"] == "main"]
    diag = [t for t in tasks if t["set"] == "diagnostic"]
    pairs = {pair for t in main for pair in t.get("pair_ids", [])}
    by_kind = Counter(t["variant_kind"] for t in main if t.get("pair_id") and t["variant_kind"] != "base")

    def dist(f):
        return dict(sorted(Counter(f(t) for t in main).items()))

    answers = defaultdict(Counter)
    for t in main:
        if t["q"].answer["kind"] == "category":
            answers[t["q"].kind][t["q"].answer["value"]] += 1
    t = cfg["targets"]
    skills = dist(lambda x: x["q"].skill)
    return {
        "dataset_version": cfg["dataset_version"],
        "dataset_purpose": manifest["dataset_purpose"],
        "manifest_sha256": manifest["manifest_sha256"],
        "attempts": attempts,
        "accepted_base_groups": len(accepted),
        "accepted_variants": len(variants),
        "rejections": dict(Counter(r for e in ledger for r in e["reasons"])),
        "base_attempts": base_attempts,
        "yield": {
            "base_accepted_over_attempted": round(len(accepted) / max(1, base_attempts), 3),
            "variants_accepted_over_attempted": round(len(variants) / max(1, attempts - base_attempts), 3),
        },
        "accepted_answerable_tasks": len(main),
        "distinct_scenes": len({x["scene"].scene_id for x in main}),
        "groups": len({x["group_id"] for x in main}),
        "skills": skills,
        "pairs": len(pairs),
        "pair_members_by_variant": dict(by_kind),
        "diagnostics": len(diag),
        "splits": units["report"]["counts"],
        "split_units": units["report"],
        "category_balance": {k: dict(v) for k, v in answers.items()},
        "themes": dist(lambda x: x["scene"].theme),
        "layout_families": dist(lambda x: x["scene"].layout_family()),
        "targets": t,
        "shortfalls": {
            k: max(0, t[k] - v)
            for k, v in {**skills, "pairs": len(pairs), "diagnostics": len(diag), "total": len(main)}.items()
            if k in t and v < t[k]
        },
        "audit_status": {
            "human_audit_planned": cfg["audit_worksheet_size"],
            "human_reviewed": 0,
            "reviewers": 0,
            "inter_reviewer_agreement": None,
            "note": "No human review has been performed; the worksheet is prepared only.",
        },
    }


def _contact_sheet(images: list[Path], labels: list[str], out: Path, cols: int = 5) -> None:
    from PIL import Image, ImageDraw

    if not images:
        return
    cw, ch = 384, 288
    rows = (len(images) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cw, rows * (ch + 20)), (255, 255, 255))
    d = ImageDraw.Draw(sheet)
    for k, (p, lab) in enumerate(zip(images, labels, strict=True)):
        im = Image.open(p).convert("RGB").resize((cw, ch))
        x, y = (k % cols) * cw, (k // cols) * (ch + 20)
        sheet.paste(im, (x, y + 20))
        d.text((x + 4, y + 4), lab, fill=(0, 0, 0))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)


def _write_samples(
    out: Path, cfg: dict[str, Any], priv: list[dict[str, Any]], pub: dict[str, list[dict[str, Any]]]
) -> None:
    dev_pub = {r["task_id"]: r for r in pub["dev"]}
    dev = [p for p in priv if p["task_id"] in dev_pub and p["set"] == "main"]
    by_skill: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in sorted(dev, key=lambda r: hid(r["task_id"], "sample")):
        by_skill[p["skill"]].append(p)
    chosen: list[dict[str, Any]] = []
    k = 0
    while len(chosen) < cfg["samples"] and any(by_skill.values()):
        for s in sorted(by_skill):
            if by_skill[s] and len(chosen) < cfg["samples"]:
                chosen.append(by_skill[s].pop(0))
        k += 1
    sdir = out / "samples"
    (sdir / "images").mkdir(parents=True, exist_ok=True)
    jsonl(sdir / "tasks.jsonl", [dev_pub[c["task_id"]] for c in chosen])
    jsonl(
        sdir / "sample_keys.jsonl",
        [
            {k: c[k] for k in ("task_id", "answer", "skill", "kind", "pump_id", "variant_kind", "evidence")}
            for c in chosen
        ],
    )
    traces = {
        json.loads(line)["scene_id"]: json.loads(line)
        for line in (out / "private" / "validation.jsonl").read_text(encoding="utf-8").splitlines()
    }
    jsonl(sdir / "sample_validation.jsonl", [traces[c["scene_id"]] for c in chosen])
    for c in chosen:
        shutil.copyfile(out / c["image"], sdir / "images" / Path(c["image"]).name)
    _contact_sheet(
        [sdir / "images" / Path(c["image"]).name for c in chosen],
        [f"{c['task_id']} {c['skill']}" for c in chosen],
        sdir / "contact_sheet.png",
    )
    # stratified human-audit worksheet (public fields only; answers are NOT included)
    allpub = {r["task_id"]: r for k in ("dev", "frozen") for r in pub[k]}
    strata: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for p in priv:
        if p["set"] == "main":
            strata[(p["skill"], p["variant_kind"])].append(p)
    rows: list[dict[str, Any]] = []
    keys = sorted(strata)
    idx = 0
    while len(rows) < cfg["audit_worksheet_size"] and keys:
        key = keys[idx % len(keys)]
        if strata[key]:
            rows.append(strata[key].pop(0))
        else:
            keys.remove(key)
            continue
        idx += 1
    (out / "audit").mkdir(exist_ok=True)
    with (out / "audit" / "human_audit_worksheet.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "task_id",
                "image",
                "question",
                "stratum",
                "reviewer_answer",
                "image_sufficient(Y/N)",
                "ambiguous(Y/N)",
                "notes",
            ]
        )
        for r in rows:
            w.writerow(
                [
                    r["task_id"],
                    r["image"],
                    allpub[r["task_id"]]["question"],
                    f"{r['skill']}/{r['variant_kind']}",
                    "",
                    "",
                    "",
                    "",
                ]
            )
    (out / "audit" / "audit_status.json").write_text(
        json.dumps(
            {
                "planned": len(rows),
                "reviewed_by_humans": 0,
                "reviewers": 0,
                "agreement": None,
                "statement": "Worksheet prepared; zero tasks have been reviewed by a human.",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


# ------------------------------------------------------------------ audit


def _manifest_file_drift(root: Path, files: dict[str, str]) -> list[str]:
    drift = []
    root = root.resolve()
    for name, digest in files.items():
        relative = PurePosixPath(name)
        path = root.joinpath(*relative.parts)
        if (
            relative.is_absolute()
            or relative.as_posix() != name
            or ".." in relative.parts
            or "\\" in name
            or ":" in name
            or not path.resolve().is_relative_to(root)
            or not path.is_file()
            or _is_link(path)
            or sha(path.read_bytes()) != digest
        ):
            drift.append(name)
    return sorted(drift)


def _audit_x_selection(
    root: Path,
    private_tasks: list[dict[str, Any]],
    public_ids: dict[str, set[str]],
    public_files: dict[str, str],
    drift: list[str],
) -> dict[str, Any]:
    file = root / X_SELECTION_PATH
    if X_SELECTION_PATH not in public_files:
        present = file.exists()
        return {"present": present, "valid": not present}
    if X_SELECTION_PATH in drift:
        return {"present": file.exists(), "valid": False}
    try:
        stored = json.loads(file.read_text(encoding="utf-8"))
        expected = select_balanced_x(private_tasks)
    except (ValueError, KeyError, TypeError):
        return {"present": True, "valid": False}
    matched_public_tasks = all(
        set(cohort["task_ids"]) <= public_ids["dev" if split == "dev" else "frozen"]
        for split, cohort in expected["splits"].items()
    )
    return {
        "present": True,
        "valid": stored == expected and matched_public_tasks,
        "splits": _x_selection_summary(expected),
    }


def audit_dataset(
    root: Path,
    rebuild_cfg: Path | None = None,
    workers: int = 1,
    *,
    holdout_seed_file: Path | None = None,
) -> dict[str, Any]:
    priv = [json.loads(line) for line in (root / "private" / "answers.jsonl").read_text(encoding="utf-8").splitlines()]
    findings: dict[str, Any] = {}
    # group / lineage leakage
    split_by_group: dict[str, set[str]] = defaultdict(set)
    for p in priv:
        split_by_group[p["group_id"]].add("dev" if p["split"] == "dev" else "frozen")
    findings["groups_in_multiple_splits"] = sum(1 for v in split_by_group.values() if len(v) > 1)
    img_split: dict[str, set[str]] = defaultdict(set)
    for p in priv:
        img_split[p["image"]].add("dev" if p["split"] == "dev" else "frozen")
    findings["images_in_multiple_splits"] = sum(1 for v in img_split.values() if len(v) > 1)
    seeds_by_split = {
        s: {p["seed"].split("|")[0] for p in priv if ("dev" if p["split"] == "dev" else "frozen") == s}
        for s in ("dev", "frozen")
    }
    findings["seed_overlap_dev_frozen"] = len(seeds_by_split["dev"] & seeds_by_split["frozen"])
    # layout family overlap is reported, not a leak by itself: only two families exist
    fam = {
        s: {p["layout_family"] for p in priv if ("dev" if p["split"] == "dev" else "frozen") == s}
        for s in ("dev", "frozen")
    }
    findings["layout_families"] = {k: sorted(v) for k, v in fam.items()}
    # private fields in public records
    leaked, answers_text = 0, [json.dumps(p["answer"], sort_keys=True) for p in priv]
    seeds = {p["seed"] for p in priv}
    seed_prefixes = {s.split(":", 1)[0] for s in seeds}
    seeds.update(prefix for prefix in seed_prefixes if re.fullmatch(r"[0-9a-f]{64}", prefix))
    public_ids: dict[str, set[str]] = defaultdict(set)
    for f in sorted((root / "public").glob("*.jsonl")):
        raw = f.read_text(encoding="utf-8")
        for line in raw.splitlines():
            rec = json.loads(line)
            if set(rec) != PUBLIC_KEYS:
                leaked += 1
            else:
                public_ids[f.stem].add(rec["task_id"])
        leaked += sum(1 for s in seeds if s in raw)
    findings["public_records_with_private_fields_or_seeds"] = leaked
    findings["private_answer_records"] = len(answers_text)
    pairs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in priv:
        for pair_id in row.get("pair_ids", []):
            pairs[pair_id].append(row)
    bad_pairs = 0
    for members in pairs.values():
        if len(members) != 2:
            bad_pairs += 1
            continue
        base, variant = sorted(members, key=lambda row: row["variant_kind"] != "base")
        same_question = all(
            base.get(key) == variant.get(key)
            for key in ("group_id", "split", "kind", "pump_id", "role", "target_unit")
        )
        valid_kind = variant["variant_kind"] in {"semantic", "nuisance", "preserving"}
        flips = not answers_agree(base["answer"], variant["answer"])
        bad_pairs += not (
            same_question and base["variant_kind"] == "base" and valid_kind
            and flips == (variant["variant_kind"] == "semantic")
        )
    findings["question_pairs_checked"] = len(pairs)
    findings["invalid_question_pairs"] = bad_pairs
    # hash drift: manifest recomputation + optional repeated pinned build
    man = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    claimed = man.pop("manifest_sha256", None)
    drift = _manifest_file_drift(root, {**man["public_files"], **man["private_commitments"]})
    purpose = man.get("dataset_purpose", "repro")
    commitment = man.get("seed_commitment_sha256")
    findings["dataset_purpose"] = purpose
    findings["manifest_sha256_valid"] = claimed == sha(canonical_json(man))
    findings["dataset_purpose_valid"] = (
        purpose == "repro" and commitment is None
        or purpose == "measured_holdout"
        and isinstance(commitment, str)
        and bool(re.fullmatch(r"[0-9a-f]{64}", commitment))
        and not _in_checkout(root.resolve())
    )
    findings["files_with_hash_drift"] = drift
    findings["x_balanced_selection"] = _audit_x_selection(
        root, priv, public_ids, man["public_files"], drift
    )
    if holdout_seed_file is not None and (rebuild_cfg is None or purpose != "measured_holdout"):
        raise ValueError("holdout seed file is only used to rebuild a measured holdout")
    if rebuild_cfg:
        if purpose == "measured_holdout":
            if holdout_seed_file is None:
                raise ValueError("rebuilding a measured holdout requires its local seed file")
            if sha(_holdout_seed(holdout_seed_file).encode("ascii")) != commitment:
                raise ValueError("holdout seed file does not match the manifest commitment")
        with TemporaryDirectory(prefix="panelproof-audit-", dir=root.resolve().parent) as scratch:
            rep = build_dataset(
                rebuild_cfg, Path(scratch) / "rebuild", workers, holdout_seed_file=holdout_seed_file
            )
            findings["rebuild_manifest_equal"] = rep["manifest_sha256"] == claimed
    # cue association: visible ALARM state vs the answer class, by question kind
    cue: dict[str, Any] = {}
    for kind in ("state", "consistency"):
        rows = [p for p in priv if p["kind"] == kind and p["set"] == "main"]
        classes = sorted({p["answer"]["value"] for p in rows})
        on = [p for p in rows if p["alarm_on"]]
        off = [p for p in rows if not p["alarm_on"]]
        rate = lambda sub, c: round(sum(1 for p in sub if p["answer"]["value"] == c) / max(1, len(sub)), 3)  # noqa: E731
        cue[kind] = {
            "n": len(rows),
            "classes": {
                c: {"overall": rate(rows, c), "alarm_on": rate(on, c), "alarm_off": rate(off, c)} for c in classes
            },
            "max_abs_shift_pp": round(100 * max((abs(rate(on, c) - rate(off, c)) for c in classes), default=0), 1),
        }
    findings["answer_class_counts"] = cue
    findings["pass"] = (
        findings["groups_in_multiple_splits"] == 0
        and findings["images_in_multiple_splits"] == 0
        and findings["seed_overlap_dev_frozen"] == 0
        and leaked == 0
        and bad_pairs == 0
        and not drift
        and findings["manifest_sha256_valid"]
        and findings["dataset_purpose_valid"]
        and findings["x_balanced_selection"]["valid"]
        and findings.get("rebuild_manifest_equal", True)
    )
    return findings


def main_build(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="panelproof build-dataset")
    ap.add_argument("--config", default=str(repo_root() / "configs" / "benchmark.yaml"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--holdout-seed-file", type=Path, help="local seed file for a measured holdout")
    a = ap.parse_args(argv)
    try:
        rep = build_dataset(Path(a.config), Path(a.out), a.workers, holdout_seed_file=a.holdout_seed_file)
    except (OSError, ValueError) as error:
        ap.error(str(error))
    print(
        json.dumps(
            {
                k: rep[k]
                for k in (
                    "manifest_sha256",
                    "dataset_purpose",
                    "accepted_answerable_tasks",
                    "skills",
                    "pairs",
                    "diagnostics",
                    "splits",
                    "shortfalls",
                    "attempts",
                )
            },
            indent=2,
        )
    )
    return 0


def main_audit(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="panelproof audit-dataset")
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--rebuild-config", default=None)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--out", default=None)
    ap.add_argument("--holdout-seed-file", type=Path, help="matching local seed file for a holdout rebuild")
    a = ap.parse_args(argv)
    try:
        f = audit_dataset(
            Path(a.dataset),
            Path(a.rebuild_config) if a.rebuild_config else None,
            a.workers,
            holdout_seed_file=a.holdout_seed_file,
        )
    except (OSError, ValueError) as error:
        ap.error(str(error))
    if a.out:
        Path(a.out).write_text(json.dumps(f, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(f, indent=2))
    return 0 if f["pass"] else 1
