"""Offline DEMO adapter (INTERIM shim for the PP-12 runner's mock provider).

Produces attempts for conditions C0/C1/C3 without any network access. Every row carries
`mock: true`; reports built from them are bannered DEMO ONLY. Behaviour is a *simulation*,
not evidence about real models:
  C0  no evidence -> prior guesses
  C1  noisy gauge reading (one tick off 20%) + 8% equipment-association swaps
  C3  verified readings supplied as text -> rule slips 6% of the time
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from .question_bridge import UNIT_ORDER
from .rule_bridge import pump_state
from .units import convert_milli, from_milli_kpa, to_milli_kpa

MODEL = "demo-offline-mock"
PROMPT_VERSION = "demo-0"


def _readings(trace: dict[str, Any], pump_id: str) -> dict[str, dict[str, Any]] | None:
    p = next((x for x in trace["pumps"] if x.get("pump_id") == pump_id and x["verdict"] == "verified"), None)
    return p and {"gauges": p["gauges"], "run": p["run"], "alarm": p["alarm"]}


def _answer(
    task: dict[str, Any], rd: dict[str, Any], rng: random.Random, cond: str, noise: float = 0.20
) -> dict[str, Any]:
    g = rd["gauges"]
    noisy: dict[str, int] = {}
    for role in ("INLET", "OUTLET"):
        v = g[role]["reading_milli"]
        if cond == "C1" and rng.random() < noise:
            v += rng.choice([-1, 1]) * g[role]["minor_tick_milli"]
        noisy[role] = v
    if cond == "C1" and rng.random() < 0.08:  # association error: read the other gauge
        noisy["INLET"], noisy["OUTLET"] = noisy["OUTLET"], noisy["INLET"]
        g = {"INLET": g["OUTLET"], "OUTLET": g["INLET"]}
    mk = {r: to_milli_kpa(noisy[r], g[r]["unit"]) for r in noisy}
    run = rd["run"] if not (cond == "C3" and rng.random() < 0.06) else not rd["run"]
    state = pump_state(run, mk["INLET"], mk["OUTLET"])
    k = task["kind"]
    if k == "read":
        r = task["role"]
        return {"kind": "numeric", "value_milli": noisy[r], "unit": g[r]["unit"]}
    if k == "convert":
        r = task["role"]
        return {
            "kind": "numeric",
            "value_milli": convert_milli(noisy[r], g[r]["unit"], task["target_unit"]),
            "unit": task["target_unit"],
        }
    if k == "delta":
        return {"kind": "numeric", "value_milli": from_milli_kpa(mk["OUTLET"] - mk["INLET"], "kPa"), "unit": "kPa"}
    if k == "state":
        return {"kind": "category", "value": state}
    exp = state == "LOW_PRESSURE"
    return {"kind": "category", "value": "CONSISTENT" if rd["alarm"] == exp else "CONTRADICTION"}


def _prior(task: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    k = task["kind"]
    if k == "state":
        return {"kind": "category", "value": rng.choice(["STOPPED", "NORMAL", "LOW_PRESSURE"])}
    if k == "consistency":
        return {"kind": "category", "value": rng.choice(["CONSISTENT", "CONTRADICTION"])}
    unit = task["target_unit"] or "kPa"
    scale = {"kPa": 300_000, "bar": 3000, "psi": 45_000}[unit if unit in UNIT_ORDER else "kPa"]
    return {"kind": "numeric", "value_milli": rng.randrange(0, 2 * scale), "unit": unit}


def generate_demo_attempts(root: Path, split: str | None = None, seed: int = 11) -> list[dict[str, Any]]:
    answers = [json.loads(x) for x in (root / "private" / "answers.jsonl").read_text(encoding="utf-8").splitlines()]
    traces = {
        r["scene_id"]: r["trace"]
        for r in (
            json.loads(x) for x in (root / "private" / "validation.jsonl").read_text(encoding="utf-8").splitlines()
        )
    }
    out: list[dict[str, Any]] = []
    for t in answers:
        if t["set"] != "main" or (split and t["split"] not in split.split(",")):
            continue
        rd = _readings(traces[t["scene_id"]], t["pump_id"])
        if rd is None:
            continue
        for cond in ("C0", "C1", "C3"):
            rng = random.Random(f"{seed}|{t['task_id']}|{cond}")
            roll = rng.random()
            status, resp = "ok", None
            if roll < 0.03:
                status = "parse_error"
            elif roll < 0.04:
                status = "timeout"
            else:
                resp = _prior(t, rng) if cond == "C0" else _answer(t, rd, rng, cond)
                if resp["kind"] == "numeric" and rng.random() < 0.01:
                    resp = {"kind": "numeric", "value_milli": "n/a", "unit": resp["unit"]}  # schema-invalid sample
            out.append(
                {
                    "task_id": t["task_id"],
                    "model": MODEL,
                    "condition": cond,
                    "prompt_version": PROMPT_VERSION,
                    "status": status,
                    "response": resp,
                    "latency_ms": round(300 + 900 * rng.random(), 1),
                    "tokens": 400 if cond == "C0" else 1300 if cond == "C1" else 600,
                    "cost_usd": 0.0,
                    "cached": rng.random() < 0.1,
                    "mock": True,
                    "label": "DEMO ONLY",
                }
            )
    return out


def write_attempts(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")


def mock_attempts_for_rows(
    rows: list[dict[str, Any]],
    traces_by_scene: dict[str, dict[str, Any]],
    models: tuple[tuple[str, float], ...] = (("demo-a", 0.1), ("demo-b", 0.25), ("demo-c", 0.4)),
    seed: int = 5,
) -> list[dict[str, Any]]:
    """C1 attempts from several mock models for the Arena fixture. DEMO ONLY."""
    out: list[dict[str, Any]] = []
    for t in rows:
        rd = _readings(traces_by_scene[t["scene_id"]], t["pump_id"])
        if rd is None:
            continue
        for name, noise in models:
            rng = random.Random(f"{seed}|{name}|{t['task_id']}")
            resp = _answer(t, rd, rng, "C1", noise)
            out.append(
                {
                    "task_id": t["task_id"],
                    "model": name,
                    "condition": "C1",
                    "status": "ok",
                    "response": resp,
                    "latency_ms": round(300 + 900 * rng.random(), 1),
                    "mock": True,
                    "label": "DEMO ONLY",
                }
            )
    return out
