"""Matched experiment conditions and benchmark metrics (PP-13).

Conditions
  C0  text-only (no image, no readings)            core
  C1  full panel image                             core
  C3  transcribed verified visible readings (text) core; no verdict, no private keys
  C2  evidence crops, C4 image + readings          optional (not wired in this release)

The Rust scorer (crates/scoring, PP-08) is the production scorer; `score_answer` here is the Python
reference used for the offline fixture and parity tests. Mock outputs are always labelled DEMO ONLY.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .adapters import PublicInput
from .evaluate import (
    C3Observations,
    EvalLimits,
    input_selection_sha256,
    prepare_c3_observations,
    public_input_sha256,
)
from .measured_cohort import (
    FROZEN_SPLITS,
    X_SCOPES,
    frozen_splits,
    load_frozen_public_tasks,
    validate_measured_x_scope,
)
from .question_bridge import answer_value, score_answer
from .scene import canonical_json

CORE_CONDITIONS = ("C0", "C1", "C3")
OK_STATUS = "ok"
FAILURE_STATUSES = ("parse_error", "provider_error", "timeout", "refusal")
BOOTSTRAP_REPS = 1000
BOOTSTRAP_SEED = 20261124


# ------------------------------------------------------------------ scoring


def score_attempt(task: dict[str, Any], attempt: dict[str, Any]) -> str:
    """correct | incorrect | invalid | failed (no usable completion)."""
    if attempt.get("status") != OK_STATUS:
        return "failed"
    return score_answer(task["answer"], attempt.get("response"))


def selection_hash(task_ids: list[str], conditions: list[str]) -> str:
    h = hashlib.sha256()
    h.update(json.dumps({"tasks": sorted(task_ids), "conditions": sorted(conditions)}, sort_keys=True).encode())
    return h.hexdigest()


def _holdout_digest(manifest: dict[str, Any] | None) -> str:
    if not isinstance(manifest, dict) or manifest.get("dataset_purpose") != "measured_holdout":
        raise PermissionError("measured report requires a private holdout manifest")
    commitment = manifest.get("seed_commitment_sha256")
    if not isinstance(commitment, str) or not re.fullmatch(r"[a-f0-9]{64}", commitment):
        raise PermissionError("measured report requires the private holdout seed commitment")
    body = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    digest = hashlib.sha256(canonical_json(body)).hexdigest()
    if manifest.get("manifest_sha256") != digest:
        raise PermissionError("measured report manifest checksum does not match its contents")
    return digest


def require_freeze(manifest: dict[str, Any] | None, approval: dict[str, Any] | None, sel_hash: str) -> None:
    """Require a private holdout and approval bound to its checksum and the task selection."""
    digest = _holdout_digest(manifest)
    approved_by = approval.get("approved_by") if isinstance(approval, dict) else None
    if (
        not isinstance(approved_by, str)
        or not approved_by.strip()
        or approval.get("selection_hash") != sel_hash
        or approval.get("manifest_sha256") != digest
    ):
        raise PermissionError("measured report requires recorded approval for this holdout and selection")


def _holdout_inputs(
    root: Path, manifest: dict[str, Any], selected: set[str]
) -> tuple[C3Observations, dict[str, str]]:
    cohort = load_frozen_public_tasks(root, manifest, selected)
    public_files = manifest["public_files"]

    limits = EvalLimits()
    root = root.resolve()
    for rel_image in sorted({task.image_path for task in cohort}):
        path = (root / rel_image).resolve()
        if not path.is_relative_to(root):
            raise PermissionError("approved PNG is outside the holdout root")
        try:
            with path.open("rb") as stream:
                image = stream.read(limits.max_image_bytes + 1)
        except OSError as exc:
            raise PermissionError("measured report requires all approved holdout PNGs") from exc
        if len(image) > limits.max_image_bytes or hashlib.sha256(image).hexdigest() != public_files.get(rel_image):
            raise PermissionError("approved PNG does not match the holdout manifest")
    try:
        observations = prepare_c3_observations(cohort, root, limits)
    except ValueError as exc:
        raise PermissionError(f"could not independently recover approved C3 observations: {exc}") from None
    digests = {
        condition: input_selection_sha256({
            task.task_id: public_input_sha256(
                PublicInput(
                    task.question, task.public_rules, task.response_schema,
                    visible_readings=observations.readings_by_task[task.task_id] if condition == "C3" else None,
                ),
                public_files[task.image_path] if condition == "C1" else None,
            )
            for task in cohort
        })
        for condition in CORE_CONDITIONS
    }
    return observations, digests


def _measured_provenance(
    tasks: dict[str, dict[str, Any]],
    attempts: list[dict[str, Any]],
    manifest: dict[str, Any],
    approval: dict[str, Any] | None,
    split: str,
    root: Path,
    x_scope: str = "balanced",
) -> dict[str, Any]:
    if not attempts:
        raise PermissionError("measured report requires nonempty model attempts")
    selected_splits = set(split.split(","))
    by_model: dict[tuple[str, str, str], dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    run_ids: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for attempt in attempts:
        tid = attempt["task_id"]
        task = tasks.get(tid)
        if not task or task["set"] != "main" or task["split"] not in selected_splits:
            raise PermissionError("measured attempts must use the selected frozen answerable tasks")
        model = (attempt["provider"], attempt["model"], attempt["model_revision"])
        condition = attempt["condition"]
        ids = by_model[model][condition]
        if condition not in CORE_CONDITIONS or tid in ids or attempt["mock"]:
            raise PermissionError("measured report refuses duplicate, mock or unsupported-condition attempts")
        ids.add(tid)
        run_ids[model].add(attempt["run_id"])
    if len({model[1] for model in by_model}) != len(by_model):
        raise PermissionError("measured report cannot mix provider identities or revisions for one model ID")
    identities = [
        {"provider": model[0], "model_id": model[1], "model_revision": model[2]} for model in sorted(by_model)
    ]
    approved_models = approval.get("models") if isinstance(approval, dict) else None
    if (
        not isinstance(approved_models, list)
        or len(approved_models) != len(identities)
        or any(model not in approved_models for model in identities)
    ):
        raise PermissionError("measured report requires approval for the exact provider, model and revision set")
    if approval.get("x_scope", "balanced") != x_scope:
        raise PermissionError("measured report requires approval for the requested X scope")
    selected: set[str] = set()
    for by_condition in by_model.values():
        if set(by_condition) != set(CORE_CONDITIONS):
            raise PermissionError("measured report requires exact C0, C1 and C3 runs for every model")
        first = by_condition["C0"]
        if not first or any(ids != first for ids in by_condition.values()):
            raise PermissionError("measured report requires the same nonempty task selection for every condition")
        require_freeze(manifest, approval, selection_hash(list(first), list(CORE_CONDITIONS)))
        selected = first
    x_task_count = validate_measured_x_scope(root, manifest, tasks, selected, x_scope)
    observations, approved_inputs = _holdout_inputs(root, manifest, selected)
    input_runs: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    c3_runs: dict[tuple[str, str], set[str]] = defaultdict(set)
    for attempt in attempts:
        condition = attempt["condition"]
        run_key = (attempt["run_id"], condition, attempt["public_inputs_sha256"])
        input_runs[run_key].add(attempt["task_id"])
        if condition == "C3":
            key = (attempt["run_id"], attempt["c3_observations_sha256"])
            c3_runs[key].add(attempt["task_id"])
    if len(c3_runs) != len({run_id for run_id, _ in c3_runs}):
        raise PermissionError("C3 run ID is bound to conflicting observation digests")
    for (_, digest), ids in c3_runs.items():
        readings = {tid: observations.readings_by_task[tid] for tid in ids}
        if digest != C3Observations(readings, 0).digest:
            raise PermissionError("C3 run observations do not match the independently recovered holdout readings")
    for (_, condition, digest), ids in input_runs.items():
        if ids != selected or digest != approved_inputs[condition]:
            raise PermissionError(f"{condition} run inputs do not match the approved holdout cohort")
    return {
        "dataset_manifest_sha256": manifest["manifest_sha256"],
        "selection_hash": approval["selection_hash"],
        "x_scope": x_scope,
        "x_task_count": x_task_count,
        "c3_observations_sha256": observations.digest,
        "public_inputs_sha256": approved_inputs,
        "models": [
            {**identity, "run_ids": sorted(run_ids[key])} for identity, key in zip(identities, sorted(by_model), strict=True)
        ],
    }


# ------------------------------------------------------------------ aggregation


def _rate(n: int, d: int) -> float | None:
    return round(n / d, 4) if d else None


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """rows: scored attempts with `outcome`. Returns counts and both accuracy denominators."""
    c = Counter(r["outcome"] for r in rows)
    attempted = len(rows)
    completed = sum(1 for r in rows if r["status"] == OK_STATUS)
    valid = c["correct"] + c["incorrect"]
    failures = Counter(r["status"] for r in rows if r["status"] != OK_STATUS)
    failures["invalid_response"] = c["invalid"]
    return {
        "attempted": attempted,
        "completed": completed,
        "valid": valid,
        "correct": c["correct"],
        "valid_only_accuracy": _rate(c["correct"], valid),
        "all_attempt_accuracy": _rate(c["correct"], attempted),
        "failures": {k: v for k, v in sorted(failures.items()) if v},
        "denominators": {"valid_only": valid, "all_attempt": attempted},
    }


def _pairs(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        ids = r.get("pair_ids") or ([r["pair_id"]] if r.get("pair_id") else [])
        for pair in ids:
            by[pair + "|" + r["kind"]].append(r)
    return by


def pair_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Semantic / nuisance / preserving pair statistics over rows of ONE (model, condition)."""
    out: dict[str, Any] = {}
    for vk in ("semantic", "nuisance", "preserving"):
        n = both_correct = sensitive = n_sens = invariant = n_inv = 0
        for group in _pairs(rows).values():
            base = next((r for r in group if r["variant_kind"] == "base"), None)
            var = next((r for r in group if r["variant_kind"] == vk), None)
            if not base or not var:
                continue
            n += 1
            both_correct += base["outcome"] == "correct" and var["outcome"] == "correct"
            if base["outcome"] in ("correct", "incorrect") and var["outcome"] in ("correct", "incorrect"):
                same_ref = answer_value(base["answer"]) == answer_value(var["answer"])
                changed = base["response"] != var["response"]
                if same_ref:
                    n_inv += 1
                    invariant += not changed
                else:
                    n_sens += 1
                    # directional: the response moved and the new response is the correct new answer
                    sensitive += changed and var["outcome"] == "correct"
        out[vk] = {
            "pairs": n,
            "pair_correctness": _rate(both_correct, n),
            "directional_sensitivity": _rate(sensitive, n_sens) if vk == "semantic" else None,
            "invariance": _rate(invariant, n_inv) if vk != "semantic" else None,
            "both_correct": both_correct,
            "denominators": {"sensitivity": n_sens, "invariance": n_inv},
        }
    return out


def group_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by[r["group_id"]].append(r)
    accs = {g: sum(r["outcome"] == "correct" for r in v) / len(v) for g, v in by.items() if len(v) >= 2}
    all_correct = sum(1 for g, a in accs.items() if a == 1.0)
    return {
        "groups_with_2plus_tasks": len(accs),
        "worst_group_accuracy": round(min(accs.values()), 4) if accs else None,
        "all_variants_correct_groups": all_correct,
        "all_variants_correct_rate": _rate(all_correct, len(accs)),
    }


def bootstrap_ci(
    rows_by_group: dict[str, list[int]],
    reps: int = BOOTSTRAP_REPS,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Base-group cluster bootstrap of all-attempt accuracy; rows_by_group maps group -> [0/1 correct,...]."""
    groups = sorted(rows_by_group)
    if not groups:
        return {"n_groups": 0}
    rng = random.Random(seed)
    stats = []
    for _ in range(reps):
        k = c = 0
        for _g in groups:
            v = rows_by_group[groups[rng.randrange(len(groups))]]
            k += sum(v)
            c += len(v)
        stats.append(k / c)
    stats.sort()
    return {
        "n_groups": len(groups),
        "reps": reps,
        "seed": seed,
        "lo95": round(stats[int(0.025 * reps)], 4),
        "hi95": round(stats[int(0.975 * reps) - 1], 4),
    }


def grounding_gain(by_cond: dict[str, list[dict[str, Any]]]) -> dict[str, Any] | None:
    """Matched C1 - C0 on tasks that have a *completed, valid* score in both conditions."""
    if "C0" not in by_cond or "C1" not in by_cond:
        return None
    a = {r["task_id"]: r for r in by_cond["C1"]}
    b = {r["task_id"]: r for r in by_cond["C0"]}
    both = sorted(set(a) & set(b))
    if not both:
        return None
    acc1 = sum(a[t]["outcome"] == "correct" for t in both) / len(both)
    acc0 = sum(b[t]["outcome"] == "correct" for t in both) / len(both)
    groups: dict[str, list[int]] = defaultdict(list)
    for t in both:
        groups[a[t]["group_id"]].append(int(a[t]["outcome"] == "correct") - int(b[t]["outcome"] == "correct"))
    rng = random.Random(BOOTSTRAP_SEED)
    names = sorted(groups)
    boots = []
    for _ in range(BOOTSTRAP_REPS):
        s = n = 0
        for _g in names:
            v = groups[names[rng.randrange(len(names))]]
            s += sum(v)
            n += len(v)
        boots.append(s / n)
    boots.sort()
    return {
        "matched_tasks": len(both),
        "C1_accuracy": round(acc1, 4),
        "C0_accuracy": round(acc0, 4),
        "gain": round(acc1 - acc0, 4),
        "n_groups": len(names),
        "bootstrap_reps": BOOTSTRAP_REPS,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "lo95": round(boots[int(0.025 * BOOTSTRAP_REPS)], 4),
        "hi95": round(boots[int(0.975 * BOOTSTRAP_REPS) - 1], 4),
    }


def build_report(
    tasks: dict[str, dict[str, Any]],
    attempts: list[dict[str, Any]],
    *,
    split: str | None = None,
    conditions: tuple[str, ...] = CORE_CONDITIONS,
) -> dict[str, Any]:
    """Score all attempts and aggregate. `tasks` maps task_id -> private record (answer, skill, ...)."""
    mock = any(a.get("mock") for a in attempts)
    scored: list[dict[str, Any]] = []
    unknown = 0
    for a in attempts:
        t = tasks.get(a["task_id"])
        if t is None or t["set"] != "main" or (split and t["split"] not in split.split(",")):
            unknown += t is None
            continue
        scored.append(
            {
                **{
                    k: t[k]
                    for k in ("skill", "kind", "difficulty", "group_id", "pair_id", "variant_kind", "answer", "split")
                },
                "pair_ids": t.get("pair_ids", []),
                "task_id": a["task_id"],
                "model": a["model"],
                "condition": a["condition"],
                "status": a["status"],
                "response": a.get("response"),
                "outcome": score_attempt(t, a),
                "latency_ms": a.get("latency_ms"),
                "cost_usd": a.get("cost_usd"),
                "cached": a.get("cached", False),
                "tokens": a.get("tokens", 0),
            }
        )
    models = sorted({r["model"] for r in scored})
    # matched selection: tasks that have an attempt row for every compared core condition for that model
    report: dict[str, Any] = {
        "banner": "DEMO ONLY - mock outputs, not a measurement" if mock else "DEVELOPMENT - unapproved report",
        "mock": mock,
        "dataset_split": split,
        "conditions": list(conditions),
        "unknown_task_attempts_ignored": unknown,
        "models": {},
    }
    for m in models:
        mrows = [r for r in scored if r["model"] == m]
        by_cond: dict[str, list[dict[str, Any]]] = {c: [r for r in mrows if r["condition"] == c] for c in conditions}
        present = [c for c in conditions if by_cond[c]]
        per_cond_ids = {c: {r["task_id"] for r in by_cond[c]} for c in present}
        matched = set.intersection(*per_cond_ids.values()) if per_cond_ids else set()
        missing = {c: len(set.union(*per_cond_ids.values()) - per_cond_ids[c]) for c in present} if per_cond_ids else {}
        mrep: dict[str, Any] = {
            "matched_task_count": len(matched),
            "tasks_missing_a_condition": missing,
            "selection_hash": selection_hash(sorted(matched), list(present)),
            "conditions": {},
        }
        for c in present:
            rows = [r for r in by_cond[c] if r["task_id"] in matched]
            lat = sorted(r["latency_ms"] for r in rows if r["latency_ms"] is not None)
            costs = [r["cost_usd"] for r in rows if r["cost_usd"] is not None]
            by_skill = {
                skill: [r for r in rows if r["skill"] == skill]
                for skill in sorted({r["skill"] for r in rows})
            }
            operating_rules = (
                {"delta": "state", "inlet_floor": "inlet_state"}
                if any(r["kind"] == "inlet_state" for r in rows) else {}
            )
            mrep["conditions"][c] = {
                **summarize(rows),
                "ci_all_attempt_accuracy": _accuracy_interval(rows),
                "by_skill": {
                    skill: {
                        **summarize(part),
                        "ci_all_attempt_accuracy": _accuracy_interval(part),
                    }
                    for skill, part in by_skill.items()
                },
                **({"by_operating_rule": _by_operating_rule(rows, operating_rules)} if operating_rules else {}),
                "by_difficulty": {
                    d: summarize([r for r in rows if r["difficulty"] == d])
                    for d in ("easy", "medium", "hard")
                    if any(r["difficulty"] == d for r in rows)
                },
                "pairs": pair_metrics(rows),
                **group_metrics(rows),
                "latency_ms": {"mean": round(sum(lat) / len(lat), 1), "p95": lat[int(0.95 * (len(lat) - 1))]}
                if lat
                else None,
                "cost_usd_total": round(sum(costs), 4) if costs else None,
                "cache_hit_rate": _rate(sum(1 for r in rows if r["cached"]), len(rows)),
                "tokens_total": sum(r["tokens"] for r in rows),
            }
        mrep["grounding_gain_C1_minus_C0"] = grounding_gain(
            {c: [r for r in by_cond[c] if r["task_id"] in matched] for c in present}
        )
        report["models"][m] = mrep
    return report


def _accuracy_interval(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        groups[row["group_id"]].append(int(row["outcome"] == "correct"))
    return bootstrap_ci(groups)


def _by_operating_rule(rows: list[dict[str, Any]], rules: dict[str, str]) -> dict[str, Any]:
    report = {}
    for name, kind in rules.items():
        cases = [row for row in rows if row["kind"] == kind]
        if cases:
            report[name] = {
                **summarize(cases),
                "ci_all_attempt_accuracy": _accuracy_interval(cases),
                "pairs": pair_metrics(cases),
            }
    return report


# ------------------------------------------------------------------ IO


def load_tasks(root: Path, *, expected_sha256: str | None = None) -> dict[str, dict[str, Any]]:
    path = root / "private" / "answers.jsonl"
    data = path.read_bytes()
    if expected_sha256 is not None and hashlib.sha256(data).hexdigest() != expected_sha256:
        raise PermissionError("private answers do not match the holdout manifest")
    return {r["task_id"]: r for r in (json.loads(x) for x in data.decode().splitlines())}


def load_attempts(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def render_markdown(rep: dict[str, Any]) -> str:
    L = [f"# PanelProof run report - {rep['banner']}", ""]
    if provenance := rep.get("provenance"):
        L += [
            f"Holdout manifest SHA-256 `{provenance['dataset_manifest_sha256']}`",
            f"Selection SHA-256 `{provenance['selection_hash']}`",
            f"X scope `{provenance['x_scope']}` ({provenance['x_task_count']} consistency tasks)",
            f"Verified C3 observation SHA-256 `{provenance['c3_observations_sha256']}`",
            "",
        ]
        for model in provenance["models"]:
            runs = ", ".join(f"`{run_id}`" for run_id in model["run_ids"])
            L.append(f"- `{model['provider']}/{model['model_id']}` at `{model['model_revision']}`, runs {runs}")
        L.append("")
    if rep["mock"]:
        L += [
            "> **DEMO ONLY.** These outputs come from the offline mock adapter. They demonstrate the report format "
            "and must not be cited as model performance.",
            "",
        ]
    for m, mr in rep["models"].items():
        L += [
            f"## Model `{m}`",
            "",
            f"Matched tasks: {mr['matched_task_count']} (selection hash `{mr['selection_hash'][:16]}`); "
            f"tasks missing a condition: {mr['tasks_missing_a_condition']}",
            "",
            "| Cond | attempted | completed | valid | correct | valid-only acc | all-attempt acc (95% CI) | failures |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for c, s in mr["conditions"].items():
            ci = s["ci_all_attempt_accuracy"]
            L.append(
                f"| {c} | {s['attempted']} | {s['completed']} | {s['valid']} | {s['correct']} | {s['valid_only_accuracy']} "
                f"(n={s['valid']}) | {s['all_attempt_accuracy']} (n={s['attempted']}; {ci.get('lo95')}-{ci.get('hi95')}, "
                f"{ci.get('n_groups')} groups, {ci.get('reps')} reps, seed {ci.get('seed')}) | {s['failures']} |"
            )
        g = mr["grounding_gain_C1_minus_C0"]
        if g:
            L += [
                "",
                f"Grounding gain C1-C0: **{g['gain']}** on {g['matched_tasks']} matched tasks "
                f"({g['lo95']} to {g['hi95']}, {g['n_groups']} groups).",
            ]
        for c, s in mr["conditions"].items():
            L += [
                "",
                f"### {c} detail",
                "",
                "| skill | valid | correct | valid-only | all-attempt | 95% group interval |",
                "|---|---|---|---|---|---|",
            ]
            for k, v in s["by_skill"].items():
                ci = v.get("ci_all_attempt_accuracy")
                interval = f"{ci.get('lo95')}–{ci.get('hi95')} ({ci['n_groups']} groups)" if ci else "—"
                L.append(
                    f"| {k} | {v['valid']} | {v['correct']} | {v['valid_only_accuracy']} | {v['all_attempt_accuracy']} "
                    f"| {interval} |"
                )
            if operating_rules := s.get("by_operating_rule"):
                L += [
                    "",
                    "| operating-state rule | attempts | correct | all-attempt | 95% group interval | semantic pairs |",
                    "|---|---|---|---|---|---|",
                ]
                for rule, stats in operating_rules.items():
                    ci = stats["ci_all_attempt_accuracy"]
                    L.append(
                        f"| {rule} | {stats['attempted']} | {stats['correct']} | {stats['all_attempt_accuracy']} "
                        f"| {ci.get('lo95')}–{ci.get('hi95')} ({ci['n_groups']} groups) "
                        f"| {stats['pairs']['semantic']['pairs']} |"
                    )
            L += ["", "| difficulty | valid | correct | valid-only | all-attempt |", "|---|---|---|---|---|"]
            for k, v in s["by_difficulty"].items():
                L.append(
                    f"| {k} | {v['valid']} | {v['correct']} | {v['valid_only_accuracy']} | {v['all_attempt_accuracy']} |"
                )
            p = s["pairs"]
            L += [
                "",
                f"Pairs - semantic: {p['semantic']['pairs']} (pair correctness {p['semantic']['pair_correctness']}, "
                f"directional sensitivity {p['semantic']['directional_sensitivity']}); nuisance: {p['nuisance']['pairs']} "
                f"(pair correctness {p['nuisance']['pair_correctness']}, invariance {p['nuisance']['invariance']}); "
                f"preserving: {p['preserving']['pairs']} (both-correct {p['preserving']['both_correct']}).",
                f"Worst-group accuracy {s['worst_group_accuracy']} over {s['groups_with_2plus_tasks']} groups; "
                f"all-variants-correct {s['all_variants_correct_groups']}.",
                f"Latency {s['latency_ms']}; cost USD {s['cost_usd_total']}; cache-hit rate {s['cache_hit_rate']}.",
            ]
        L.append("")
    L += [
        "## Interpretation limits",
        "",
        "- Intervals are base-group cluster bootstraps; groups are not independent draws from a wider population.",
        "- Small skill cohorts have limited precision. With few groups, an interval can be unstable or degenerate.",
        "- C3 supplies verified readings as text and therefore isolates rule reasoning; it is not a vision score.",
        "- Missing responses are excluded from the matched set and listed separately; they are never counted as correct.",
        "- The missing-evidence diagnostic set is reported separately and is not part of these aggregates.",
    ]
    return "\n".join(L) + "\n"


def main_metrics(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="panelproof metrics")
    ap.add_argument("--tasks", required=True, help="dataset directory built by build-dataset")
    ap.add_argument("--attempts", required=True, action="append", help="attempts JSONL; repeat for multiple runs")
    ap.add_argument("--out", required=True)
    ap.add_argument(
        "--split", default=None, help="comma list of splits to include, e.g. dev or frozen_main,frozen_heldout_style"
    )
    ap.add_argument(
        "--attempt-format",
        choices=("demo", "contract"),
        default="demo",
        help="demo: rows from `demo-attempts`; contract: attempts.jsonl written by `python -m panelproof.evaluate`",
    )
    ap.add_argument("--rust-pp", default=None, help="path to the Rust `pp` binary: cross-check scoring against it")
    ap.add_argument("--measured", action="store_true", help="require dataset freeze + access approval")
    ap.add_argument(
        "--x-scope", choices=X_SCOPES, default="balanced", help="measured X cohort (balanced by default)"
    )
    ap.add_argument("--approval", default=None, help="approval JSON for the holdout, selection and pinned models")
    a = ap.parse_args(argv)
    root = Path(a.tasks)
    manifest = approval = None
    expected_answers = None
    if a.measured:
        if a.attempt_format != "contract":
            raise PermissionError("measured report requires contract attempts with adjacent run manifests")
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        _holdout_digest(manifest)
        commitments = manifest.get("private_commitments")
        expected_answers = commitments.get("private/answers.jsonl") if isinstance(commitments, dict) else None
        if not isinstance(expected_answers, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_answers):
            raise PermissionError("measured report requires a commitment for private answers")
        approval = json.loads(Path(a.approval).read_text(encoding="utf-8")) if a.approval else None
        try:
            a.split = ",".join(frozen_splits(a.split or ",".join(FROZEN_SPLITS)))
        except ValueError as exc:
            raise PermissionError("measured report requires frozen splits") from exc
    tasks = load_tasks(root, expected_sha256=expected_answers)
    if a.attempt_format == "contract":
        from .contract_attempts import load_contract_attempts

        attempts = [row for path in a.attempts for row in load_contract_attempts(Path(path), measured=a.measured)]
    else:
        attempts = [row for path in a.attempts for row in load_attempts(Path(path))]
    provenance = (
        _measured_provenance(tasks, attempts, manifest, approval, a.split, root, a.x_scope) if a.measured else None
    )
    rep = build_report(tasks, attempts, split=a.split)
    if provenance:
        rep["banner"] = "MEASURED"
        rep["provenance"] = provenance
    if a.rust_pp:
        from .contract_attempts import rust_parity

        parity = rust_parity(tasks, attempts, executable=a.rust_pp)
        rep["rust_scoring_parity"] = parity if parity is not None else {"status": "not run: pp binary not found"}
        if parity and parity["mismatch_count"]:
            raise RuntimeError(f"Rust scorer disagrees on {parity['mismatch_count']} attempts: {parity['mismatches'][:3]}")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(rep, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "report.md").write_text(render_markdown(rep), encoding="utf-8")
    scored = [(a_, tasks[a_["task_id"]]) for a_ in attempts if a_["task_id"] in tasks]
    with (out / "per_attempt_scores.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["task_id", "model", "condition", "status", "outcome", "skill", "difficulty", "group_id"])
        for at, t in scored:
            w.writerow(
                [
                    at["task_id"],
                    at["model"],
                    at["condition"],
                    at["status"],
                    score_attempt(t, at),
                    t["skill"],
                    t["difficulty"],
                    t["group_id"],
                ]
            )
    print(rep["banner"], "->", out / "report.md")
    return 0


_ = math  # keep import for downstream numeric helpers
