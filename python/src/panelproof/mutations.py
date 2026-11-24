"""Controlled variants of a base scene: semantic flip, meaning-preserving, nuisance, missing evidence.

Each variant keeps the base group/lineage, records a private field-level diff, and is checked
against the intended answer change before it is accepted.
"""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass, field
from typing import Any

from .interim_rules import THRESHOLD_MKPA, pump_state
from .render import THEMES
from .scene import Gauge, Scene, load_config, place_glare, scene_from_dict
from .units import to_milli_kpa

HIDDEN_UNIVERSE_MAX_MKPA = 1_500_000  # plausible upper bound for an unseen gauge (kPa * 1000)


@dataclass
class Variant:
    kind: str  # semantic | preserving | nuisance | missing
    edit: str
    pump_id: str | None
    scene: Scene
    diff: list[dict[str, Any]] = field(default_factory=list)
    expected: dict[str, Any] = field(default_factory=dict)


def _flatten(obj: Any, path: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(_flatten(v, f"{path}.{k}" if path else str(k)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(_flatten(v, f"{path}[{i}]"))
    else:
        out[path] = obj
    return out


def scene_diff(a: Scene, b: Scene) -> list[dict[str, Any]]:
    fa, fb = _flatten(a.to_dict()), _flatten(b.to_dict())
    return [
        {"path": k, "before": fa.get(k), "after": fb.get(k)}
        for k in sorted(set(fa) | set(fb))
        if fa.get(k) != fb.get(k) and k != "seed"
    ]


def _clone(scene: Scene, tag: str) -> Scene:
    d = copy.deepcopy(scene.to_dict())
    d["seed"] = f"{scene.seed}|{tag}"
    return scene_from_dict(d)


def _margin_ok(p, ticks: int = 1) -> bool:
    gi, go = p.gauge("INLET"), p.gauge("OUTLET")
    return abs(p.delta_mkpa() - THRESHOLD_MKPA) >= ticks * (gi.minor_mkpa + go.minor_mkpa)


def make_semantic_flip(base: Scene, rng: random.Random, tag: str = "sem") -> Variant | None:
    """One material change that flips the answer. Prefers a needle crossing the threshold."""
    s = _clone(base, tag)
    p = s.pumps[rng.randrange(len(s.pumps))]
    options = ["needle_cross", "needle_cross", "alarm_toggle", "run_toggle"]
    if not p.run:
        options = ["needle_cross_run_on", "alarm_toggle"]
    edit = rng.choice(options)
    before = {"state": p.state(), "x": p.alarm_consistent()}
    if edit.startswith("needle_cross"):
        if edit == "needle_cross_run_on":
            return None  # crossing is only observable with RUN on; handled by run_toggle in other draws
        gauge = p.gauge(rng.choice(["INLET", "OUTLET"]))
        want_normal = p.state() != "NORMAL"
        cands = []
        for idx in range(1, gauge.n_minor):
            old = gauge.value_milli
            gauge.value_milli = gauge.min_milli + idx * gauge.minor_milli
            ok = (p.delta_mkpa() >= THRESHOLD_MKPA) == want_normal and p.delta_mkpa() >= 0 and _margin_ok(p)
            gauge.value_milli = old
            if ok:
                cands.append(idx)
        if not cands:
            return None
        gauge.value_milli = gauge.min_milli + rng.choice(cands) * gauge.minor_milli
        edit = f"needle_cross:{gauge.role}"
        direction = (
            "outlet_up"
            if (gauge.role == "OUTLET") == want_normal
            else "inlet_up"
            if want_normal is False
            else "inlet_down"
        )
    elif edit == "alarm_toggle":
        p.alarm = not p.alarm
        direction = "alarm"
    else:  # run_toggle: only meaningful when the toggle changes the state
        p.run = not p.run
        direction = "run"
    after = {"state": p.state(), "x": p.alarm_consistent()}
    if after == before:
        return None
    v = Variant(
        "semantic", edit, p.pump_id, s, scene_diff(base, s), {"before": before, "after": after, "direction": direction}
    )
    return v if not validate_variant(base, v) else None


def make_preserving(base: Scene, rng: random.Random, tag: str = "unit") -> Variant | None:
    """Display-unit conversion on one gauge that preserves the physical value exactly."""
    cfg = load_config()
    s = _clone(base, tag)
    p = s.pumps[rng.randrange(len(s.pumps))]
    g = p.gauge(rng.choice(["INLET", "OUTLET"]))
    target = {"kPa": "bar", "bar": "kPa", "psi": None}[g.unit]
    if target is None:
        return None
    scales = list(cfg["scales"][target])
    rng.shuffle(scales)
    for lo, hi, step, mpm in scales:
        mn, mx, st = lo * 1000, hi * 1000, step * 1000
        minor = st // mpm
        ng = Gauge(g.role, target, mn, mx, st, mpm, 0, g.cx, g.cy, g.r)
        # physical value in target-unit milli: exact only for kPa<->bar (factor 100)
        v = g.value_milli // 100 if g.unit == "kPa" else g.value_milli * 100
        if g.unit == "kPa" and g.value_milli % 100:
            continue
        if (v - mn) % minor or not (1 <= (v - mn) // minor <= ng.n_minor - 1):
            continue
        ng.value_milli = v
        if ng.value_mkpa != g.value_mkpa:
            continue
        p.gauges[p.gauges.index(g)] = ng
        var = Variant(
            "preserving",
            f"unit_conversion:{g.role}:{g.unit}->{target}",
            p.pump_id,
            s,
            scene_diff(base, s),
            {"physical_mkpa": g.value_mkpa},
        )
        return var if not validate_variant(base, var) else None
    return None


def make_nuisance(base: Scene, rng: random.Random, tag: str = "nui") -> Variant | None:
    s = _clone(base, tag)
    kinds = ["font_scale", "gauge_order", "lamp_order", "glare"]
    non_teal = [t for t in THEMES if t != "teal"]
    if base.theme != "teal":
        kinds.append("theme")
    edit = rng.choice(kinds)
    if edit == "theme":
        s.theme = rng.choice([t for t in non_teal if t != base.theme])
    elif edit == "font_scale":
        s.font_scale = rng.choice([x for x in (0.95, 1.0, 1.05) if x != base.font_scale])
    elif edit in ("gauge_order", "lamp_order"):
        p = s.pumps[rng.randrange(len(s.pumps))]
        if edit == "gauge_order":
            p.gauges.reverse()
            from .scene import layout_pump

            layout_pump(p, p.module)
        else:
            p.lamp_order.reverse()
            from .scene import layout_pump

            layout_pump(p, p.module)
    else:
        for _ in range(20):
            gl = place_glare(rng, s)
            if gl:
                s.glare = gl
                break
        else:
            return None
    if not scene_diff(base, s):
        return None
    var = Variant("nuisance", edit, None, s, scene_diff(base, s))
    return var if not validate_variant(base, var) else None


def feasible_states(p, hidden_role: str) -> set[str]:
    """States still consistent with the visible evidence when one gauge is covered."""
    vis = p.gauge("OUTLET" if hidden_role == "INLET" else "INLET")
    vm = vis.value_mkpa
    states: set[str] = set()
    for hm in range(0, HIDDEN_UNIVERSE_MAX_MKPA + 1, 10_000):
        i, o = (hm, vm) if hidden_role == "INLET" else (vm, hm)
        if i <= o:
            states.add(pump_state(p.run, i, o))
    return states


def make_missing(base: Scene, rng: random.Random, tag: str = "miss") -> Variant | None:
    s = _clone(base, tag)
    runners = [p for p in s.pumps if p.run]
    if not runners:
        return None
    p = rng.choice(runners)
    role = rng.choice(["INLET", "OUTLET"])
    states = feasible_states(p, role)
    if len(states) < 2:
        role = "OUTLET" if role == "INLET" else "INLET"
        states = feasible_states(p, role)
    if len(states) < 2:
        return None  # redundant evidence: not an abstention example
    p.covered = [role]
    var = Variant(
        "missing",
        f"cover:{role}",
        p.pump_id,
        s,
        scene_diff(base, s),
        {"feasible_states": sorted(states), "answer": "INSUFFICIENT"},
    )
    return var if not validate_variant(base, var) else None


def truth_signature(scene: Scene) -> dict[str, Any]:
    """Order-independent physical truth (ignores appearance / permutation)."""
    return {
        p.pump_id: {
            "run": p.run,
            "alarm": p.alarm,
            "state": p.state(),
            "delta": p.delta_mkpa(),
            "inlet": p.gauge("INLET").value_mkpa,
            "outlet": p.gauge("OUTLET").value_mkpa,
            "consistent": p.alarm_consistent(),
        }
        for p in scene.pumps
    }


def validate_variant(base: Scene, v: Variant) -> list[str]:
    errs: list[str] = []
    sb, sv = truth_signature(base), truth_signature(v.scene)
    if v.kind == "semantic":
        changed = [k for k in sb if sb[k] != sv[k]]
        if changed != [v.pump_id]:
            errs.append(f"semantic edit touched pumps {changed}")
        if (
            sb[v.pump_id]["state"] == sv[v.pump_id]["state"]
            and sb[v.pump_id]["consistent"] == sv[v.pump_id]["consistent"]
        ):
            errs.append("answer did not change")
        if v.edit.startswith("needle_cross"):
            d0, d1 = sb[v.pump_id]["delta"], sv[v.pump_id]["delta"]
            if (d0 >= THRESHOLD_MKPA) == (d1 >= THRESHOLD_MKPA):
                errs.append("needle did not cross threshold")
            if v.expected.get("after", {}).get("state") == "NORMAL" and not d1 > d0:
                errs.append("direction: expected delta increase")
            if v.expected.get("after", {}).get("state") == "LOW_PRESSURE" and not d1 < d0:
                errs.append("direction: expected delta decrease")
            if not _margin_ok(v.scene.pump(v.pump_id)):
                errs.append("variant violates threshold margin")
    elif v.kind in ("preserving", "nuisance"):
        if sb != sv:
            errs.append("physical truth changed")
    elif v.kind == "missing":
        if len(v.expected.get("feasible_states", [])) < 2:
            errs.append("unique answer remains")
        if sb != sv:
            errs.append("truth altered")
    return errs


def make_variants(base: Scene, rng: random.Random) -> dict[str, Variant | None]:
    return {
        "semantic": make_semantic_flip(base, rng),
        "preserving": make_preserving(base, rng),
        "nuisance": make_nuisance(base, rng),
        "missing": make_missing(base, rng),
    }


def main_variants(argv: list[str]) -> int:  # pragma: no cover - thin CLI
    import argparse
    import json

    from .scene import generate_scene

    ap = argparse.ArgumentParser(prog="panelproof variants")
    ap.add_argument("--seed", default="variants")
    ap.add_argument("--pairs", type=int, default=100)
    a = ap.parse_args(argv)
    counts: dict[str, int] = {"semantic": 0, "preserving": 0, "nuisance": 0, "missing": 0}
    attempts = 0
    i = 0
    while min(counts.values()) < a.pairs and i < a.pairs * 20:
        base = generate_scene(f"{a.seed}:{i:05d}")
        rng = random.Random(f"{a.seed}:{i:05d}:v")
        for k, v in make_variants(base, rng).items():
            attempts += 1
            if v and counts[k] < a.pairs:
                assert not validate_variant(base, v), (k, validate_variant(base, v))
                counts[k] += 1
        i += 1
    print(
        json.dumps(
            {
                "accepted_pairs": counts,
                "base_scenes_tried": i,
                "draws": attempts,
                "to_milli_kpa_check": to_milli_kpa(1000, "bar"),
            }
        )
    )
    return 0
