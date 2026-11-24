import hashlib
import json

import pytest

from panelproof.cli import main
from panelproof.export import X_SELECTION_PATH, select_balanced_x
from panelproof.measured_cohort import validate_measured_x_scope
from panelproof.metrics import CORE_CONDITIONS, selection_hash
from panelproof.scene import canonical_json
from panelproof.schemas import SCHEMA_VERSION, PublicTask


def _jsonl(path, rows):
    path.write_bytes(b"".join(canonical_json(row) + b"\n" for row in rows))


@pytest.fixture
def holdout(tmp_path):
    root = tmp_path / "private-holdout"
    (root / "private").mkdir(parents=True)
    (root / "public").mkdir()

    def task(task_id, split, *, skill, kind, alarm=False, answer="NORMAL", pairs=None):
        return {
            "task_id": task_id,
            "split": split,
            "set": "main",
            "kind": kind,
            "skill": skill,
            "alarm_on": alarm,
            "answer": {"kind": "category", "value": answer},
            "pair_ids": pairs or [],
            "sentinel": "private-answer-ledger-only",
        }

    rows = []
    splits = {"frozen_main": "main", "frozen_heldout_style": "style", "dev": "dev"}
    for split, short in splits.items():
        rows.extend(
            [
                task(short + "-r", split, skill="R", kind="read"),
                task(short + "-c", split, skill="C", kind="conversion"),
                task(short + "-m", split, skill="M", kind="state"),
            ]
        )
        for cell in range(4):
            expected, observed = divmod(cell, 2)
            rows.append(
                task(
                    f"{short}-x{cell}",
                    split,
                    skill="X",
                    kind="consistency",
                    alarm=bool(observed),
                    answer="CONSISTENT" if observed == expected else "CONTRADICTION",
                    pairs=[short + "-pair"] if cell in {0, 1} else None,
                )
            )
    rows.append(
        task("z-surplus", "frozen_main", skill="X", kind="consistency", answer="CONSISTENT")
    )
    _jsonl(root / "private" / "answers.jsonl", rows)
    selection = select_balanced_x(rows)
    (root / X_SELECTION_PATH).write_bytes(canonical_json(selection))
    public = [
        PublicTask(
            schema_version=SCHEMA_VERSION,
            task_id=row["task_id"],
            image_path="images/fixture.png",
            question="Read the panel.",
            public_rules="Use the stated threshold.",
            response_schema={"type": "object"},
        )
        for row in rows
        if row["split"] != "dev"
    ]
    _jsonl(root / "public" / "frozen.jsonl", [task.model_dump(mode="json") for task in public])
    body = {
        "dataset_purpose": "measured_holdout",
        "seed_commitment_sha256": "a" * 64,
        "private_commitments": {
            rel: hashlib.sha256((root / rel).read_bytes()).hexdigest()
            for rel in ("private/answers.jsonl", X_SELECTION_PATH)
        },
        "public_files": {
            "public/frozen.jsonl": hashlib.sha256(
                (root / "public/frozen.jsonl").read_bytes()
            ).hexdigest()
        },
    }
    manifest = {**body, "manifest_sha256": hashlib.sha256(canonical_json(body)).hexdigest()}
    (root / "manifest.json").write_bytes(canonical_json(manifest))
    return root, manifest, {row["task_id"]: row for row in rows}, selection


def test_prepare_measured_is_balanced_sorted_public_and_leaves_holdout_untouched(
    holdout, tmp_path, capsys
):
    root, manifest, _, _ = holdout
    source = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    output = tmp_path / "measured.jsonl"
    args = ["prepare-measured-cohort", "--dataset", str(root), "--out", str(output)]
    assert main(args) == 0
    plan = json.loads(capsys.readouterr().out)
    data = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    ids = [row["task_id"] for row in data]
    assert ids == sorted(ids) and len(ids) == plan["selected_count"] == 14
    assert plan["x_scope"] == "balanced" and plan["x_task_count"] == 8
    assert plan["manifest_sha256"] == manifest["manifest_sha256"]
    assert plan["selection_hash"] == selection_hash(ids, list(CORE_CONDITIONS))
    assert all(not tid.startswith("dev") for tid in ids) and "z-surplus" not in ids
    assert all(set(row) == set(PublicTask.model_fields) for row in data)
    assert {path: path.read_bytes() for path in root.rglob("*") if path.is_file()} == source

    full = tmp_path / "full.jsonl"
    assert (
        main(
            [
                "prepare-measured-cohort",
                "--dataset",
                str(root),
                "--out",
                str(full),
                "--split",
                "frozen_main",
                "--x-scope",
                "full",
            ]
        )
        == 0
    )
    full_plan = json.loads(capsys.readouterr().out)
    assert full_plan["x_scope"] == "full" and full_plan["x_task_count"] == 5
    assert full_plan["selected_count"] == 8 and "z-surplus" in full.read_text(encoding="utf-8")


def test_selected_measured_x_must_be_complete_per_included_split(holdout):
    root, manifest, tasks, selection = holdout
    balanced = set(selection["splits"]["frozen_main"]["task_ids"])
    assert validate_measured_x_scope(root, manifest, tasks, {"main-r"}, "balanced") == 0
    assert validate_measured_x_scope(root, manifest, tasks, balanced | {"main-r"}, "balanced") == 4
    for invalid in (balanced - {"main-x1"}, balanced | {"z-surplus"}, balanced | {"style-r"}):
        with pytest.raises(PermissionError, match="complete X cohort"):
            validate_measured_x_scope(root, manifest, tasks, invalid, "balanced")
    assert validate_measured_x_scope(root, manifest, tasks, balanced | {"z-surplus"}, "full") == 5
    with pytest.raises(PermissionError, match="complete X cohort"):
        validate_measured_x_scope(root, manifest, tasks, balanced, "full")


def test_tampered_sidecar_and_output_inside_holdout_are_refused(holdout, tmp_path, capsys):
    root, _, _, _ = holdout
    with pytest.raises(SystemExit) as error:
        main(["prepare-measured-cohort", "--dataset", str(root), "--out", str(root / "new.jsonl")])
    assert error.value.code == 2 and "outside the holdout root" in capsys.readouterr().err
    sidecar = root / X_SELECTION_PATH
    sidecar.write_bytes(sidecar.read_bytes() + b"\n")
    out = tmp_path / "bad.jsonl"
    with pytest.raises(SystemExit) as error:
        main(["prepare-measured-cohort", "--dataset", str(root), "--out", str(out)])
    assert (
        error.value.code == 2 and "does not match the holdout manifest" in capsys.readouterr().err
    )
    assert not out.exists()


def test_cohort_output_inside_any_checkout_is_refused(holdout, tmp_path, capsys):
    root, _, _, _ = holdout
    checkout = tmp_path / "other-checkout"
    (checkout / ".git").mkdir(parents=True)
    out = checkout / "selected.jsonl"
    with pytest.raises(SystemExit) as error:
        main(["prepare-measured-cohort", "--dataset", str(root), "--out", str(out)])
    assert error.value.code == 2 and "all Git checkouts" in capsys.readouterr().err
    assert not out.exists()
