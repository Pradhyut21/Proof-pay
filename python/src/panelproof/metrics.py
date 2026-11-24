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
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .interim_questions import score_answer

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


def require_freeze(manifest: dict[str, Any] | None, approval: dict[str, Any] | None, sel_hash: str) -> None:
    """Measured runs only after dataset freeze and recorded access approval."""
    if not manifest or "manifest_sha256" not in manifest:
        raise PermissionError("measured run refused: no frozen dataset manifest")
    if not approval or approval.get("selection_hash") != sel_hash or not approval.get("approved_by"):
        raise PermissionError("measured run refused: no recorded access approval for this selection hash")


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
        if r.get("pair_id"):
            by[r["pair_id"] + "|" + r["kind"]].append(r)
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
                same_ref = base["answer"] == var["answer"]
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
        "banner": "DEMO ONLY - mock outputs, not a measurement" if mock else "MEASURED",
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
            groups: dict[str, list[int]] = defaultdict(list)
            for r in rows:
                groups[r["group_id"]].append(int(r["outcome"] == "correct"))
            lat = sorted(r["latency_ms"] for r in rows if r["latency_ms"] is not None)
            costs = [r["cost_usd"] for r in rows if r["cost_usd"] is not None]
            mrep["conditions"][c] = {
                **summarize(rows),
                "ci_all_attempt_accuracy": bootstrap_ci(groups),
                "by_skill": {
                    s: summarize([r for r in rows if r["skill"] == s]) for s in sorted({r["skill"] for r in rows})
                },
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


# ------------------------------------------------------------------ IO


def load_tasks(root: Path) -> dict[str, dict[str, Any]]:
    path = root / "private" / "answers.jsonl"
    return {r["task_id"]: r for r in (json.loads(x) for x in path.read_text(encoding="utf-8").splitlines())}


def load_attempts(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def render_markdown(rep: dict[str, Any]) -> str:
    L = [f"# PanelProof run report - {rep['banner']}", ""]
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
                "| skill | valid | correct | valid-only | all-attempt |",
                "|---|---|---|---|---|",
            ]
            for k, v in s["by_skill"].items():
                L.append(
                    f"| {k} | {v['valid']} | {v['correct']} | {v['valid_only_accuracy']} | {v['all_attempt_accuracy']} |"
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
        "- C3 supplies verified readings as text and therefore isolates rule reasoning; it is not a vision score.",
        "- Missing responses are excluded from the matched set and listed separately; they are never counted as correct.",
        "- The missing-evidence diagnostic set is reported separately and is not part of these aggregates.",
    ]
    return "\n".join(L) + "\n"


def main_metrics(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="panelproof metrics")
    ap.add_argument("--tasks", required=True, help="dataset directory built by build-dataset")
    ap.add_argument("--attempts", required=True, help="attempts JSONL")
    ap.add_argument("--out", required=True)
    ap.add_argument(
        "--split", default=None, help="comma list of splits to include, e.g. dev or frozen_main,frozen_heldout_style"
    )
    ap.add_argument("--measured", action="store_true", help="require dataset freeze + access approval")
    ap.add_argument("--approval", default=None, help="JSON with selection_hash and approved_by (measured runs only)")
    a = ap.parse_args(argv)
    root = Path(a.tasks)
    tasks = load_tasks(root)
    attempts = load_attempts(Path(a.attempts))
    rep = build_report(tasks, attempts, split=a.split)
    if a.measured:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        approval = json.loads(Path(a.approval).read_text(encoding="utf-8")) if a.approval else None
        for m in rep["models"].values():
            require_freeze(manifest, approval, m["selection_hash"])
        if rep["mock"]:
            raise PermissionError("measured report refused: attempts are mock/DEMO ONLY")
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
