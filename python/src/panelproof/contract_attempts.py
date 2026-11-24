"""Bridges between the shared run/attempt contract, the metrics module and the Rust scorer.

* ``load_contract_attempts`` reads rows written by ``python -m panelproof.evaluate`` (schemas.Attempt) and maps them
  to the row shape that ``metrics.build_report`` aggregates. ``run.json`` beside the rows marks demo runs.
* ``rust_parity`` replays the scored attempts through the independent Rust scorer (``pp score``) and reports any
  task where the two implementations disagree.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .metrics import score_attempt
from .schemas import Attempt, Run

_STATUS = {
    "correct": "ok",
    "incorrect": "ok",
    "unscored": "ok",
    "invalid_response": "parse_error",
    "provider_error": "provider_error",
}


def _require_run_provenance(run_data: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    try:
        run = Run.model_validate(run_data)
        records = [Attempt.model_validate(row) for row in rows]
    except ValidationError:
        raise PermissionError("measured report requires valid attempt and adjacent run records") from None
    if run.demo_only or run.provider.casefold() == "demo":
        raise PermissionError("measured report refuses DEMO ONLY model runs")
    if not all(value and value.strip() for value in (run.provider, run.model_id, run.model_revision)):
        raise PermissionError("measured report requires a pinned provider, model and model revision")
    ids = [record.task_id for record in records]
    digest = hashlib.sha256(json.dumps(ids, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    if not ids or len(ids) != len(set(ids)) or digest != run.selected_task_ids_sha256:
        raise PermissionError("attempts must cover the exact nonempty task selection recorded by the run")
    for record in records:
        if (record.run_id, record.provider, record.model_id, record.condition, record.model_revision) != (
            run.run_id, run.provider, run.model_id, run.condition, run.model_revision
        ):
            raise PermissionError("attempt identity, revision or condition conflicts with its run record")
        if record.status == "skipped":
            raise PermissionError("measured report requires a complete frozen cohort, including all planned attempts")


def load_contract_attempts(path: Path, *, measured: bool = False) -> list[dict[str, Any]]:
    """Map schemas.Attempt rows to metrics rows. ``skipped`` attempts are not attempts and are dropped."""
    run: dict[str, Any] = {}
    run_file = path.parent / "run.json"
    if run_file.is_file():
        run = json.loads(run_file.read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if measured:
        _require_run_provenance(run, rows)
    demo = bool(run.get("demo_only"))
    out: list[dict[str, Any]] = []
    for row in rows:
        if row["status"] == "skipped":
            continue
        status = _STATUS[row["status"]]
        if row.get("error") == "provider_timeout" and status == "provider_error":
            status = "timeout"
        mock = demo or row.get("provider") == "demo"
        out.append(
            {
                "task_id": row["task_id"],
                "model": row["model_id"],
                "provider": row.get("provider"),
                "model_revision": row.get("model_revision"),
                "run_id": row.get("run_id"),
                "condition": row["condition"],
                "status": status,
                "response": row.get("parsed_answer"),
                "latency_ms": row.get("latency_ms"),
                "cost_usd": row.get("cost_usd"),
                "cached": row.get("cached"),
                "mock": mock,
                "label": "DEMO ONLY" if mock else None,
            }
        )
    return out


def _numeric_or_category(answer: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in answer.items() if k != "tolerance_milli"}


def rust_parity(
    tasks: dict[str, dict[str, Any]],
    attempts: list[dict[str, Any]],
    *,
    executable: str | os.PathLike[str] = "pp",
    timeout_seconds: float = 120,
) -> dict[str, Any] | None:
    """Return parity counts, or None when the Rust ``pp`` binary is not available."""
    binary = shutil.which(os.fspath(executable))
    if binary is None:
        return None
    by_run: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for a in attempts:
        if a["task_id"] in tasks:
            by_run[(a["model"], a["condition"])].append(a)
    checked = 0
    mismatches: list[dict[str, str]] = []
    for (model, cond), rows in sorted(by_run.items()):
        refs, preds, expect = [], [], {}
        for a in rows:
            t = tasks[a["task_id"]]
            outcome = score_attempt(t, a)
            refs.append(
                {
                    "task_id": a["task_id"],
                    "answer": _numeric_or_category(t["answer"]),
                    "tolerance_milli": t["answer"].get("tolerance_milli"),
                    "group_id": t["group_id"],
                    "pair_id": t.get("pair_id"),
                    "variant_kind": None,
                }
            )
            usable = outcome in ("correct", "incorrect")
            preds.append({"task_id": a["task_id"], "answer": _numeric_or_category(a["response"]) if usable else None})
            expect[a["task_id"]] = outcome if usable else "missing"
        with _tmp(refs) as refs_path, _tmp(preds) as preds_path:
            proc = subprocess.run(
                [binary, "score", "--refs", refs_path, "--preds", preds_path],
                capture_output=True,
                encoding="utf-8",
                timeout=timeout_seconds,
                check=False,
            )
        if proc.returncode != 0:
            raise RuntimeError(f"Rust scorer failed for {model}/{cond}: {proc.stderr.strip()[:200]}")
        rust = {r["task_id"]: r["outcome"] for r in json.loads(proc.stdout)["tasks"]}
        for task_id, want in expect.items():
            checked += 1
            if rust.get(task_id) != want:
                mismatches.append({"model": model, "condition": cond, "task_id": task_id, "python": want, "rust": str(rust.get(task_id))})
    return {"checked": checked, "mismatches": mismatches[:20], "mismatch_count": len(mismatches)}


class _tmp:
    """Temporary JSONL file path usable by a subprocess on every platform."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        import tempfile

        fd, self.path = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))

    def __enter__(self) -> str:
        return self.path

    def __exit__(self, *exc: object) -> None:
        Path(self.path).unlink(missing_ok=True)
