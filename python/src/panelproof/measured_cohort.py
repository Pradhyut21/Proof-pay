"""Prepare the public task projection for an approved measured holdout cohort."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .scene import canonical_json
from .schemas import SCHEMA_VERSION, PublicTask

FROZEN_SPLITS = ("frozen_main", "frozen_heldout_style")
X_SCOPES = ("balanced", "full")


def frozen_splits(value: str) -> tuple[str, ...]:
    names = {name.strip() for name in value.split(",")}
    if not names.issubset(FROZEN_SPLITS):
        raise ValueError("choose frozen_main, frozen_heldout_style, or both")
    return tuple(name for name in FROZEN_SPLITS if name in names)


def load_frozen_public_tasks(
    root: Path, manifest: dict[str, Any], selected: set[str]
) -> list[PublicTask]:
    public_files = manifest.get("public_files")
    if not isinstance(public_files, dict):
        raise PermissionError("measured report requires public holdout checksums")
    relative = "public/frozen.jsonl"
    try:
        public_bytes = (root / relative).read_bytes()
    except OSError as exc:
        raise PermissionError(
            "measured report requires the committed public frozen task list"
        ) from exc
    if hashlib.sha256(public_bytes).hexdigest() != public_files.get(relative):
        raise PermissionError("public frozen task list does not match the holdout manifest")
    try:
        tasks = [
            PublicTask.model_validate_json(line)
            for line in public_bytes.splitlines()
            if line.strip()
        ]
    except ValidationError:
        raise PermissionError("public frozen task list contains an invalid task") from None
    cohort = [task for task in tasks if task.task_id in selected]
    if len(cohort) != len(selected) or {task.task_id for task in cohort} != selected:
        raise PermissionError(
            "approved tasks must appear exactly once in the public frozen task list"
        )
    return sorted(cohort, key=lambda task: task.task_id)


def _available_x(tasks: dict[str, dict[str, Any]], splits: tuple[str, ...]) -> dict[str, set[str]]:
    return {
        split: {
            task_id
            for task_id, task in tasks.items()
            if task["split"] == split and task["set"] == "main" and task["kind"] == "consistency"
        }
        for split in splits
    }


def scoped_x_ids(
    root: Path,
    manifest: dict[str, Any],
    tasks: dict[str, dict[str, Any]],
    splits: tuple[str, ...],
    scope: str,
) -> set[str]:
    from .export import OLD_PUBLIC_X_SELECTION_PATH, X_CELL_NAMES, X_SELECTION_PATH

    available = _available_x(tasks, splits)
    if scope == "full":
        return set().union(*available.values())
    if not any(available.values()):
        return set()
    commitments = manifest.get("private_commitments")
    public = manifest.get("public_files", {})
    if (
        X_SELECTION_PATH in public
        or OLD_PUBLIC_X_SELECTION_PATH in public
        or (root / OLD_PUBLIC_X_SELECTION_PATH).exists()
    ):
        raise PermissionError("balanced X selection must remain private")
    try:
        data = (root / X_SELECTION_PATH).read_bytes()
    except OSError as exc:
        raise PermissionError(
            "balanced X scope requires the committed private X selection"
        ) from exc
    if not isinstance(commitments, dict) or hashlib.sha256(data).hexdigest() != commitments.get(
        X_SELECTION_PATH
    ):
        raise PermissionError("private X selection does not match the holdout manifest")
    try:
        sidecar = json.loads(data)
        if (
            sidecar["schema_version"] != SCHEMA_VERSION
            or sidecar["selector"] != "x-four-cell-pairs-v1"
        ):
            raise ValueError
        selected: set[str] = set()
        for split, eligible in available.items():
            cohort = sidecar["splits"][split]
            ids = cohort["task_ids"]
            cells = cohort["selected_cell_counts"]
            valid_status = (
                cohort["status"] == "balanced"
                if ids
                else cohort["status"] in {"missing_cell", "infeasible_with_pairs"}
            )
            if (
                not isinstance(ids, list)
                or any(not isinstance(tid, str) for tid in ids)
                or ids != sorted(set(ids))
                or not set(ids).issubset(eligible)
                or len(eligible) != cohort["eligible_count"]
                or len(ids) != cohort["selected_count"]
                or hashlib.sha256(canonical_json(ids)).hexdigest() != cohort["task_ids_sha256"]
                or set(cells) != set(X_CELL_NAMES)
                or any(
                    type(n) is not int or n < 0 or n * len(X_CELL_NAMES) != len(ids)
                    for n in cells.values()
                )
                or not valid_status
            ):
                raise ValueError
            selected.update(ids)
    except (AttributeError, KeyError, TypeError, ValueError):
        raise PermissionError(
            "private X selection is invalid for the requested frozen splits"
        ) from None
    return selected


def validate_measured_x_scope(
    root: Path,
    manifest: dict[str, Any],
    tasks: dict[str, dict[str, Any]],
    selected: set[str],
    scope: str,
) -> int:
    actual_x = {tid for tid in selected if tasks[tid]["kind"] == "consistency"}
    if actual_x:
        splits = tuple(
            split
            for split in FROZEN_SPLITS
            if any(tasks[tid]["split"] == split for tid in selected)
        )
        if scoped_x_ids(root, manifest, tasks, splits, scope) != actual_x:
            raise PermissionError(
                f"measured {scope} X scope requires the complete X cohort for each included split"
            )
    return len(actual_x)


def main_prepare_measured(argv: list[str]) -> int:
    from .export import _in_checkout
    from .metrics import CORE_CONDITIONS, _holdout_digest, load_tasks, selection_hash

    parser = argparse.ArgumentParser(prog="panelproof prepare-measured-cohort")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument(
        "--out", type=Path, required=True, help="new task JSONL file outside the holdout and Git"
    )
    parser.add_argument("--split", default=",".join(FROZEN_SPLITS))
    parser.add_argument("--x-scope", choices=X_SCOPES, default="balanced")
    args = parser.parse_args(argv)
    try:
        root = args.dataset.resolve()
        out = args.out.resolve()
        if out.is_relative_to(root) or _in_checkout(args.out.absolute()) or _in_checkout(out):
            raise ValueError("cohort output must be outside the holdout root and all Git checkouts")
        splits = frozen_splits(args.split)
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        manifest_hash = _holdout_digest(manifest)
        commitments = manifest.get("private_commitments")
        expected_answers = (
            commitments.get("private/answers.jsonl") if isinstance(commitments, dict) else None
        )
        if not isinstance(expected_answers, str):
            raise PermissionError("measured cohort requires a commitment for private answers")
        tasks = load_tasks(root, expected_sha256=expected_answers)
        x_ids = scoped_x_ids(root, manifest, tasks, splits, args.x_scope)
        selected = x_ids | {
            tid
            for tid, task in tasks.items()
            if task["set"] == "main"
            and task["split"] in splits
            and task["skill"] in {"R", "C", "M"}
        }
        if not selected:
            raise ValueError("no answerable frozen tasks were selected")
        public = load_frozen_public_tasks(root, manifest, selected)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write("".join(task.model_dump_json() + "\n" for task in public))
        print(
            json.dumps(
                {
                    "selected_count": len(selected),
                    "x_task_count": len(x_ids),
                    "x_scope": args.x_scope,
                    "splits": list(splits),
                    "conditions": list(CORE_CONDITIONS),
                    "manifest_sha256": manifest_hash,
                    "selection_hash": selection_hash(list(selected), list(CORE_CONDITIONS)),
                }
            )
        )
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Measured cohort preparation failed: {exc}\n")
    return 0
