import hashlib
import json

import pytest

from panelproof.metrics import (
    bootstrap_ci,
    build_report,
    main_metrics,
    require_freeze,
    score_attempt,
    selection_hash,
    summarize,
)
from panelproof.question_bridge import numeric
from panelproof.scene import canonical_json


def task(tid, kind="state", answer=None, group="g1", pair=None, vk="base", skill="M", diff="easy"):
    return {
        "task_id": tid,
        "set": "main",
        "split": "dev",
        "skill": skill,
        "kind": kind,
        "difficulty": diff,
        "group_id": group,
        "pair_id": pair,
        "variant_kind": vk,
        "answer": answer or {"kind": "category", "value": "NORMAL"},
    }


def att(tid, cond, resp, status="ok", model="m"):
    return {
        "task_id": tid,
        "model": model,
        "condition": cond,
        "status": status,
        "response": resp,
        "mock": True,
        "latency_ms": 100.0,
    }


def cat(v):
    return {"kind": "category", "value": v}


def test_categorical_numeric_and_failure_scoring_golden():
    t_cat = task("a")
    t_num = task("b", "read", numeric(540_000, "kPa", 20_000), skill="R")
    assert score_attempt(t_cat, att("a", "C1", cat("NORMAL"))) == "correct"
    assert score_attempt(t_cat, att("a", "C1", cat("LOW_PRESSURE"))) == "incorrect"
    assert score_attempt(t_cat, att("a", "C1", {"kind": "numeric", "value_milli": 1, "unit": "kPa"})) == "invalid"
    assert score_attempt(t_cat, att("a", "C1", None, status="timeout")) == "failed"
    ok = {"kind": "numeric", "unit": "kPa"}
    assert score_attempt(t_num, att("b", "C1", {**ok, "value_milli": 560_000})) == "correct"  # +1 tick, inclusive
    assert score_attempt(t_num, att("b", "C1", {**ok, "value_milli": 560_001})) == "incorrect"
    assert score_attempt(t_num, att("b", "C1", {**ok, "unit": "bar", "value_milli": 540_000})) == "invalid"


def test_valid_only_vs_all_attempt_denominators():
    tasks = {f"t{i}": task(f"t{i}", group=f"g{i}") for i in range(4)}
    attempts = [
        att("t0", "C1", cat("NORMAL")),
        att("t1", "C1", cat("LOW_PRESSURE")),
        att("t2", "C1", None, status="parse_error"),
        att("t3", "C1", {"kind": "numeric", "value_milli": 1, "unit": "kPa"}),
    ]
    rep = build_report(tasks, attempts, conditions=("C1",))
    s = rep["models"]["m"]["conditions"]["C1"]
    assert (s["attempted"], s["completed"], s["valid"], s["correct"]) == (4, 3, 2, 1)
    assert s["valid_only_accuracy"] == 0.5 and s["all_attempt_accuracy"] == 0.25
    assert s["failures"] == {"invalid_response": 1, "parse_error": 1}
    assert s["denominators"] == {"valid_only": 2, "all_attempt": 4}
    assert rep["banner"].startswith("DEMO ONLY")


def test_pair_metrics_sensitivity_invariance_and_all_variants_correct():
    tasks = {
        "s0": task("s0", pair="p1", vk="base", group="g1"),
        "s1": task("s1", answer=cat("LOW_PRESSURE"), pair="p1", vk="semantic", group="g1"),
        "n0": task("n0", pair="p2", vk="base", group="g2"),
        "n1": task("n1", pair="p2", vk="nuisance", group="g2"),
    }
    attempts = [
        att("s0", "C1", cat("NORMAL")),
        att("s1", "C1", cat("LOW_PRESSURE")),  # direction followed
        att("n0", "C1", cat("NORMAL")),
        att("n1", "C1", cat("LOW_PRESSURE")),  # nuisance flips the model
    ]
    c = build_report(tasks, attempts, conditions=("C1",))["models"]["m"]["conditions"]["C1"]
    assert c["pairs"]["semantic"]["pair_correctness"] == 1.0
    assert c["pairs"]["semantic"]["directional_sensitivity"] == 1.0
    assert c["pairs"]["nuisance"]["pair_correctness"] == 0.0
    assert c["pairs"]["nuisance"]["invariance"] == 0.0
    assert c["all_variants_correct_groups"] == 1 and c["groups_with_2plus_tasks"] == 2
    assert c["worst_group_accuracy"] == 0.5


def test_matched_sample_and_grounding_gain():
    tasks = {f"t{i}": task(f"t{i}", group=f"g{i // 2}") for i in range(6)}
    attempts = []
    for i in range(6):
        attempts.append(att(f"t{i}", "C1", cat("NORMAL")))  # 6/6 correct
        attempts.append(att(f"t{i}", "C0", cat("NORMAL" if i < 2 else "STOPPED")))  # 2/6 correct
    attempts.append(att("t5", "C3", cat("NORMAL")))  # C3 only covers one task -> excluded by matching
    rep = build_report(tasks, attempts)
    m = rep["models"]["m"]
    assert m["matched_task_count"] == 1
    g = m["grounding_gain_C1_minus_C0"]
    assert g["matched_tasks"] == 1 and m["tasks_missing_a_condition"]["C3"] == 5
    # without C3, all six tasks are matched and the gain is exactly (6 - 2) / 6
    rep2 = build_report(tasks, [a for a in attempts if a["condition"] != "C3"], conditions=("C0", "C1"))
    g2 = rep2["models"]["m"]["grounding_gain_C1_minus_C0"]
    assert g2["matched_tasks"] == 6 and g2["gain"] == round(4 / 6, 4)


def test_identical_inputs_give_identical_intervals_and_reports():
    groups = {f"g{i}": [1, 0, 1][: 1 + i % 3] for i in range(12)}
    assert bootstrap_ci(groups) == bootstrap_ci(groups)
    tasks = {f"t{i}": task(f"t{i}", group=f"g{i % 3}") for i in range(9)}
    attempts = [att(f"t{i}", "C1", cat("NORMAL" if i % 2 else "STOPPED")) for i in range(9)]
    r1 = json.dumps(build_report(tasks, attempts, conditions=("C1",)), sort_keys=True)
    r2 = json.dumps(build_report(tasks, attempts, conditions=("C1",)), sort_keys=True)
    assert r1 == r2


def test_summarize_empty_has_no_fake_rates():
    s = summarize([])
    assert s["valid_only_accuracy"] is None and s["all_attempt_accuracy"] is None


def holdout_manifest(**fields):
    body = {"dataset_purpose": "measured_holdout", "seed_commitment_sha256": "a" * 64, **fields}
    return {**body, "manifest_sha256": hashlib.sha256(canonical_json(body)).hexdigest()}


def test_measured_run_requires_freeze_and_approval():
    h = selection_hash(["a", "b"], ["C0", "C1"])
    manifest = holdout_manifest()
    approval = {"selection_hash": h, "approved_by": "owner", "manifest_sha256": manifest["manifest_sha256"]}
    with pytest.raises(PermissionError):
        require_freeze(None, None, h)
    with pytest.raises(PermissionError):
        require_freeze({"manifest_sha256": "a" * 64}, approval, h)
    with pytest.raises(PermissionError):
        require_freeze(holdout_manifest(dataset_purpose="repro"), approval, h)
    with pytest.raises(PermissionError):
        require_freeze(manifest, {**approval, "selection_hash": "other"}, h)
    with pytest.raises(PermissionError):
        require_freeze({**manifest, "dataset_version": "tampered"}, approval, h)
    require_freeze(manifest, approval, h)


def write_run(root, condition, ids, *, mock=False):
    root.mkdir()
    identity = {"provider": "openai_compatible", "model_id": "fixture-model", "model_revision": "fixture-v1"}
    base = {"schema_version": "1.0.0", "run_id": f"fixture-{condition}", "condition": condition, **identity}
    run = {
        **base,
        "prompt_version": "fixture-v1",
        "seed": 0,
        "max_calls": len(ids),
        "selected_task_ids_sha256": hashlib.sha256(canonical_json(ids)).hexdigest(),
        "environment_fingerprint": "synthetic contract fixture",
        "demo_only": mock,
    }
    rows = [
        {
            **base,
            "task_id": tid,
            "status": "unscored",
            "parsed_answer": cat("NORMAL"),
            "timestamp": "2026-11-24T00:00:00Z",
            "latency_ms": 1,
        }
        for tid in ids
    ]
    (root / "run.json").write_text(json.dumps(run), encoding="utf-8")
    path = root / "attempts.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path, identity


def test_measured_report_checks_holdout_approval_and_source_runs(tmp_path):
    dataset = tmp_path / "dataset"
    (dataset / "private").mkdir(parents=True)
    answers = dataset / "private" / "answers.jsonl"
    rows = [{**task(tid), "split": "frozen_main"} for tid in ("a", "b")]
    answers.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    manifest = holdout_manifest(private_commitments={"private/answers.jsonl": hashlib.sha256(answers.read_bytes()).hexdigest()})
    (dataset / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    c0, identity = write_run(tmp_path / "first", "C0", ["b", "a"])
    c1, _ = write_run(tmp_path / "second", "C1", ["a", "b"])
    empty, _ = write_run(tmp_path / "empty", "C1", [])
    mock, _ = write_run(tmp_path / "mock", "C1", ["a", "b"], mock=True)
    disjoint, _ = write_run(tmp_path / "disjoint", "C1", ["b"])
    approval = tmp_path / "approval.json"
    approval.write_text(json.dumps({
        "approved_by": "fixture approver",
        "selection_hash": selection_hash(["a", "b"], ["C0", "C1"]),
        "manifest_sha256": manifest["manifest_sha256"],
        "models": [identity],
    }), encoding="utf-8")
    out = tmp_path / "report"
    args = ["--tasks", str(dataset), "--out", str(out), "--attempt-format", "contract", "--measured", "--approval", str(approval)]

    for rejected, reason in (
        (empty, "nonempty task selection"),
        (mock, "DEMO ONLY"),
        (disjoint, "same nonempty task selection"),
    ):
        with pytest.raises(PermissionError, match=reason):
            main_metrics([*args, "--attempts", str(c0), "--attempts", str(rejected)])
        assert not out.exists()

    assert main_metrics([*args, "--attempts", str(c0), "--attempts", str(c1)]) == 0
    report = json.loads((out / "report.json").read_text())
    assert report["banner"] == "MEASURED"
    assert report["provenance"]["models"] == [{**identity, "run_ids": ["fixture-C0", "fixture-C1"]}]

    (c1.parent / "run.json").unlink()
    with pytest.raises(PermissionError, match="adjacent run records"):
        main_metrics([*args, "--attempts", str(c0), "--attempts", str(c1)])
    answers.write_text("{}", encoding="utf-8")
    with pytest.raises(PermissionError, match="answers do not match"):
        main_metrics([*args, "--attempts", str(c0), "--attempts", str(c1)])


def test_no_unapproved_report_is_labelled_measured():
    row = {**att("a", "C1", cat("NORMAL")), "mock": False}
    assert build_report({"a": task("a")}, [row])["banner"].startswith("DEVELOPMENT")
