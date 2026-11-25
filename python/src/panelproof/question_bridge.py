"""Question construction for generated scenes, built on the shared contract (``questions.build_question``).

Skills: R reading, C conversion, M composition (state / pressure difference), X consistency.
Text, public rules, response schema and reference values come from the shared builder; tolerances are one
minor tick (readings) or the composed minor ticks (differences).
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any

from .questions import AmbiguousQuestion, _category_schema, build_question
from .rules import INLET_FLOOR_RULE
from .scene import Scene
from .schemas import SCHEMA_VERSION, Pressure, Pump
from .schemas import Scene as ContractScene
from .units import convert_milli, from_milli_kpa

UNIT_ORDER = ("kPa", "bar", "psi")
STATES = ["STOPPED", "NORMAL", "LOW_PRESSURE"]


@dataclass
class Question:
    skill: str  # R | C | M | X
    kind: str  # read | convert | state | inlet_state | delta | consistency
    pump_id: str
    role: str | None
    target_unit: str | None
    text: str
    answer: dict[str, Any]
    public_rules: str
    schema: dict[str, Any]
    contract_skill: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def numeric(value_milli: int, unit: str, tol_milli: int) -> dict[str, Any]:
    return {"kind": "numeric", "value_milli": value_milli, "unit": unit, "tolerance_milli": tol_milli}


def category(value: str) -> dict[str, Any]:
    return {"kind": "category", "value": value}


def contract_scene(scene: Scene) -> ContractScene:
    """Typed contract scene (schemas.Scene) for a generated scene."""
    seed_int = int(hashlib.sha256(scene.seed.encode()).hexdigest()[:12], 16)
    return ContractScene(
        schema_version=SCHEMA_VERSION,
        base_scene_id=scene.scene_id,
        seed=seed_int,
        layout_family=scene.layout_family(),
        style_family=scene.theme,
        equipment=[
            Pump(
                id=p.pump_id,
                label=p.label,
                inlet=Pressure(value_milli=p.gauge("INLET").value_milli, unit=p.gauge("INLET").unit),
                outlet=Pressure(value_milli=p.gauge("OUTLET").value_milli, unit=p.gauge("OUTLET").unit),
                run=p.run,
                alarm=p.alarm,
            )
            for p in scene.pumps
        ],
    )


def _draft(
    scene: ContractScene,
    pump_id: str,
    kind: str,
    target_unit: str | None = None,
    *,
    uncertainty_milli_kpa: int = 0,
):
    # task_id/image_path are placeholders: the exporter assigns the real identifiers.
    return build_question(
        scene,
        pump_id,
        kind,  # type: ignore[arg-type]
        task_id="placeholder",
        image_path="images/placeholder.png",
        uncertainty_milli_kpa=uncertainty_milli_kpa,
        **({"target_unit": target_unit} if target_unit else {}),
    )


def _numeric_answer(draft, tol_milli: int) -> dict[str, Any]:
    return numeric(draft.answer.value_milli, draft.answer.unit, tol_milli)


def build_questions(scene: Scene, *, include_inlet_floor: bool = False) -> list[Question]:
    """Questions come from the shared contract builder (``questions.build_question``)."""
    cs = contract_scene(scene)
    out: list[Question] = []
    for p in scene.pumps:
        for role in ("INLET", "OUTLET"):
            g = p.gauge(role)
            if role == "OUTLET":
                # The shared builder converts outlet readings only, so conversion tasks use the outlet gauge.
                tgt = "bar" if g.unit != "bar" else "kPa"
                d = _draft(cs, p.pump_id, "convert_outlet", tgt)
                out.append(
                    Question(
                        "C",
                        "convert",
                        p.pump_id,
                        role,
                        tgt,
                        d.public.question,
                        _numeric_answer(d, max(1, convert_milli(g.minor_milli, g.unit, tgt))),
                        d.public.public_rules,
                        d.public.response_schema,
                        "conversion",
                    )
                )
            d = _draft(cs, p.pump_id, "read_inlet" if role == "INLET" else "read_outlet")
            out.append(
                Question(
                    "R",
                    "read",
                    p.pump_id,
                    role,
                    g.unit,
                    d.public.question,
                    _numeric_answer(d, g.minor_milli),
                    d.public.public_rules,
                    d.public.response_schema,
                    "reading",
                )
            )
        d = _draft(cs, p.pump_id, "operating_state")
        out.append(
            Question(
                "M", "state", p.pump_id, None, None, d.public.question, category(d.answer.value),
                d.public.public_rules, d.public.response_schema, "operational_state",
            )
        )
        gi, go = p.gauge("INLET"), p.gauge("OUTLET")
        d = _draft(cs, p.pump_id, "pressure_difference")
        out.append(
            Question(
                "M", "delta", p.pump_id, None, "kPa", d.public.question,
                _numeric_answer(d, from_milli_kpa(gi.minor_mkpa + go.minor_mkpa, "kPa")),
                d.public.public_rules, d.public.response_schema, "difference",
            )
        )
        d = _draft(cs, p.pump_id, "alarm_consistency")
        out.append(
            Question(
                "X", "consistency", p.pump_id, None, None, d.public.question, category(d.answer.value),
                d.public.public_rules, d.public.response_schema, "indicator_consistency",
            )
        )
        if include_inlet_floor:
            try:
                d = _draft(
                    cs, p.pump_id, "inlet_state", uncertainty_milli_kpa=gi.minor_mkpa
                )
            except AmbiguousQuestion:
                continue
            out.append(
                Question(
                    "M",
                    "inlet_state",
                    p.pump_id,
                    "INLET",
                    None,
                    d.public.question,
                    category(d.answer.value),
                    d.public.public_rules,
                    d.public.response_schema,
                    "operational_state",
                )
            )
    return out


def response_schema(q: Question, diagnostic: bool = False) -> dict[str, Any]:
    """Public response schema; diagnostic (missing-evidence) tasks also allow INSUFFICIENT."""
    if diagnostic and q.kind == "state":
        return _category_schema([*STATES, "INSUFFICIENT"])
    return q.schema


def answer_value(answer: dict[str, Any]) -> dict[str, Any]:
    """Return the reference value without its grading tolerance."""
    return {key: value for key, value in answer.items() if key != "tolerance_milli"}


def score_answer(answer: dict[str, Any], response: dict[str, Any] | None) -> str:
    """Deterministic python reference scoring: correct | incorrect | invalid."""
    if not response or response.get("kind") != answer["kind"]:
        return "invalid"
    if answer["kind"] == "category":
        return "correct" if response.get("value") == answer["value"] else "incorrect"
    if response.get("unit") != answer["unit"] or not isinstance(response.get("value_milli"), int):
        return "invalid"
    return (
        "correct" if abs(response["value_milli"] - answer["value_milli"]) <= answer["tolerance_milli"] else "incorrect"
    )


def answer_from_trace(q: Question, trace_pump: dict[str, Any]) -> dict[str, Any] | None:
    """Derive the answer to `q` from an independent raster-verifier pump trace."""
    if q.kind == "inlet_state":
        run = trace_pump.get("run")
        if trace_pump.get("verdict") != "verified" or type(run) is not bool:
            return None
        if not run:
            return category(INLET_FLOOR_RULE.state_for(False, 0))
        gauges = trace_pump.get("gauges")
        inlet = gauges.get("INLET") if isinstance(gauges, dict) else None
        if not isinstance(inlet, dict):
            return None
        reading = inlet.get("reading_mkpa")
        uncertainty = inlet.get("uncertainty_mkpa")
        if type(reading) is not int or type(uncertainty) is not int or uncertainty < 0:
            return None
        state = INLET_FLOOR_RULE.state_for_interval(run, reading, uncertainty)
        return category(state) if state is not None else None
    if q.kind == "read":
        g = trace_pump["gauges"][q.role]
        return numeric(g["reading_milli"], g["unit"], g["minor_tick_milli"])
    if q.kind == "convert":
        g = trace_pump["gauges"][q.role]
        return numeric(
            convert_milli(g["reading_milli"], g["unit"], q.target_unit),
            q.target_unit,
            max(1, convert_milli(g["minor_tick_milli"], g["unit"], q.target_unit)),
        )
    d = trace_pump["derived"]
    if q.kind == "state":
        return category(d["state"])
    if q.kind == "delta":
        return numeric(
            from_milli_kpa(d["delta_mkpa"], "kPa"), "kPa", from_milli_kpa(d["delta_uncertainty_mkpa"] * 2, "kPa")
        )
    if q.kind == "consistency":
        return category("CONSISTENT" if d["alarm_consistent"] else "CONTRADICTION")
    return None


def answers_agree(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if a["kind"] == "category":
        return a["value"] == b["value"]
    return a["unit"] == b["unit"] and abs(a["value_milli"] - b["value_milli"]) <= a["tolerance_milli"]
