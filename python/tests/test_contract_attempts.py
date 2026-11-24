import json
from pathlib import Path

from panelproof.contract_attempts import load_contract_attempts, rust_parity


def _row(task_id: str, status: str, answer: dict | None) -> dict:
    return {
        "task_id": task_id,
        "model_id": "m",
        "condition": "C1",
        "status": status,
        "parsed_answer": answer,
        "latency_ms": 5,
        "cost_usd": 0.0,
        "cached": False,
    }


def test_rows_map_to_metrics_shape_and_skipped_are_dropped(tmp_path: Path) -> None:
    rows = [
        _row("a", "correct", {"kind": "category", "value": "NORMAL"}),
        _row("b", "invalid_response", None),
        _row("c", "provider_error", None),
        _row("d", "skipped", None),
    ]
    path = tmp_path / "attempts.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    (tmp_path / "run.json").write_text(json.dumps({"demo_only": True}), encoding="utf-8")
    out = load_contract_attempts(path)
    assert [r["task_id"] for r in out] == ["a", "b", "c"]
    assert [r["status"] for r in out] == ["ok", "parse_error", "provider_error"]
    assert all(r["mock"] and r["label"] == "DEMO ONLY" for r in out)


def test_measured_run_is_not_labelled_demo(tmp_path: Path) -> None:
    path = tmp_path / "attempts.jsonl"
    path.write_text(json.dumps(_row("a", "unscored", {"kind": "category", "value": "NORMAL"})) + "\n", encoding="utf-8")
    (row,) = load_contract_attempts(path)
    assert row["mock"] is False and row["label"] is None


def test_rust_parity_is_none_without_binary() -> None:
    assert rust_parity({}, [], executable="definitely-not-a-real-binary") is None
