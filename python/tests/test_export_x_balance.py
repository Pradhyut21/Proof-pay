import json
import random
from collections import Counter
from itertools import product

import pytest

from panelproof.export import (
    OLD_PUBLIC_X_SELECTION_PATH,
    X_CELL_NAMES,
    X_SELECTION_PATH,
    _audit_x_selection,
    _manifest,
    canonical_json,
    select_balanced_x,
    sha,
)


def task(task_id, cell, split="dev", **fields):
    expected, observed = divmod(cell, 2)
    return {
        "task_id": task_id,
        "set": "main",
        "kind": "consistency",
        "split": split,
        "answer": {
            "kind": "category",
            "value": "CONSISTENT" if expected == observed else "CONTRADICTION",
        },
        "alarm_on": bool(observed),
        **fields,
    }


def component(prefix, cells, split="dev"):
    rows = []
    for index, cell in enumerate(cells):
        edges = [
            f"{prefix}-pair-{edge}" for edge in (index - 1, index) if 0 <= edge < len(cells) - 1
        ]
        rows.append(task(f"{prefix}-{index}", cell, split, pair_ids=edges))
    return rows


def test_balances_each_split_without_filtering_original_rows():
    rows = [
        *[task(f"dev-{cell}", cell) for cell in range(4)],
        task("dev-surplus", 0),
        *[task(f"main-{cell}", cell, "frozen_main") for cell in range(4)],
        *[task(f"style-{cell}", cell, "frozen_heldout_style") for cell in range(4)],
        task("non-x", 0, kind="state"),
        task("diagnostic", 0, set="diagnostic"),
    ]
    before = json.dumps(rows, sort_keys=True)
    result = select_balanced_x(rows)
    assert len(rows) == 15
    assert json.dumps(rows, sort_keys=True) == before
    assert select_balanced_x(reversed(rows)) == result

    for split, cohort in result["splits"].items():
        assert cohort["status"] == "balanced"
        assert cohort["eligible_count"] == (5 if split == "dev" else 4)
        assert cohort["selected_count"] == 4
        assert cohort["selected_cell_counts"] == dict.fromkeys(X_CELL_NAMES, 1)
        assert cohort["selected_max_cue_shift_pp"] == 0
        assert cohort["task_ids_sha256"] == sha(canonical_json(cohort["task_ids"]))
        assert "non-x" not in cohort["task_ids"] and "diagnostic" not in cohort["task_ids"]

    assert result["splits"]["dev"]["eligible_max_cue_shift_pp"] == pytest.approx(16.667)


def test_linked_pairs_stay_together_across_the_whole_component():
    linked = component("linked", [0, 1, 2])
    rows = [*linked, task("last-cell", 3), task("surplus", 0)]
    cohort = select_balanced_x(rows)["splits"]["dev"]
    assert cohort["task_ids"] == sorted([*(row["task_id"] for row in linked), "last-cell"])
    assert cohort["selected_component_count"] == 2
    assert cohort["selected_pair_count"] == 2


def test_exact_balance_can_be_infeasible_even_if_all_cells_are_present():
    rows = [*component("overloaded", [0, 0, 1]), task("two", 2), task("three", 3)]
    cohort = select_balanced_x(rows)["splits"]["dev"]
    assert cohort["status"] == "infeasible_with_pairs"
    assert min(cohort["eligible_cell_counts"].values()) == 1
    assert not cohort["task_ids"]
    assert cohort["selected_max_cue_shift_pp"] is None


def test_picks_a_smaller_optimum_when_the_raw_cell_bound_cannot_be_reached():
    smaller = component("balanced", [0, 1, 2, 3])
    bigger = component("extra", [0, 0, 1, 2, 3])
    cohort = select_balanced_x([*smaller, *bigger])["splits"]["dev"]
    assert min(cohort["eligible_cell_counts"].values()) == 2
    assert cohort["task_ids"] == [row["task_id"] for row in smaller]
    assert cohort["selected_pair_count"] == 3


def test_small_and_empty_cohorts_are_explicit():
    selection = select_balanced_x([task("one", 0)])
    dev = selection["splits"]["dev"]
    assert dev["status"] == "missing_cell"
    assert dev["eligible_count"] == 1 and dev["selected_count"] == 0
    assert dev["eligible_max_cue_shift_pp"] is None
    assert selection["splits"]["frozen_main"]["eligible_count"] == 0


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ([task("orphan", 0, pair_ids=["pair"])], "exactly two distinct members"),
        (
            [task("a", 0, pair_ids=["pair"]), task("b", 1, "frozen_main", pair_ids=["pair"])],
            "crosses dataset splits",
        ),
    ],
)
def test_rejects_malformed_pair_membership(rows, message):
    with pytest.raises(ValueError, match=message):
        select_balanced_x(rows)


def test_optimality_matches_brute_force_for_small_deterministic_cohorts():
    rng = random.Random(12957)
    for _ in range(18):
        shapes = [[rng.randrange(4) for _ in range(rng.randrange(1, 4))] for _ in range(6)]
        rows = [row for index, shape in enumerate(shapes) for row in component(str(index), shape)]
        largest = 0
        for bits in product((0, 1), repeat=len(shapes)):
            counts = Counter(
                cell for flag, shape in zip(bits, shapes, strict=True) if flag for cell in shape
            )
            by_cell = [counts[cell] for cell in range(4)]
            if len(set(by_cell)) == 1:
                largest = max(largest, sum(by_cell))
        assert select_balanced_x(rows)["splits"]["dev"]["selected_count"] == largest


def test_audit_requires_private_commitment_and_linked_public_tasks(tmp_path):
    rows = [task(f"t{cell}", cell) for cell in range(4)]
    plan = select_balanced_x(rows)
    path = tmp_path / X_SELECTION_PATH
    path.parent.mkdir()
    path.write_text(json.dumps(plan), encoding="utf-8")
    public_ids = {"dev": {row["task_id"] for row in rows}, "frozen": set()}
    manifest = _manifest(tmp_path, {"dataset_version": "test"}, {}, {"dataset_purpose": "repro"})
    assert X_SELECTION_PATH not in manifest["public_files"]
    assert manifest["private_commitments"][X_SELECTION_PATH] == sha(path.read_bytes())

    audited = _audit_x_selection(tmp_path, rows, public_ids, manifest, [])
    assert audited["valid"]
    assert {"task_ids", "task_ids_sha256"}.isdisjoint(audited["splits"]["dev"])
    assert not _audit_x_selection(tmp_path, rows, public_ids, manifest, [X_SELECTION_PATH])["valid"]
    assert not _audit_x_selection(tmp_path, rows, {"dev": {"t0"}, "frozen": set()}, manifest, [])[
        "valid"
    ]
    uncommitted = manifest | {"private_commitments": {}}
    assert not _audit_x_selection(tmp_path, rows, public_ids, uncommitted, [])["valid"]
    plan["splits"]["dev"]["task_ids"].remove("t0")
    path.write_text(json.dumps(plan), encoding="utf-8")
    assert not _audit_x_selection(tmp_path, rows, public_ids, manifest, [])["valid"]


def test_audit_rejects_legacy_public_selection(tmp_path):
    path = tmp_path / OLD_PUBLIC_X_SELECTION_PATH
    path.parent.mkdir()
    path.write_text("{}", encoding="utf-8")
    manifest = {"public_files": {}, "private_commitments": {}}
    finding = _audit_x_selection(tmp_path, [], {}, manifest, [])
    assert finding == {"present": True, "valid": False, "reason": "selection_exposed_publicly"}
    path.unlink()
    manifest["public_files"][X_SELECTION_PATH] = "a" * 64
    assert _audit_x_selection(tmp_path, [], {}, manifest, []) == finding
