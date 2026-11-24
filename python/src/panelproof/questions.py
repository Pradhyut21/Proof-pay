"""Build public visual questions and private reference answers from a typed scene."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .rules import PUMP_RULE, conversion_rules_text, convert_pressure
from .schemas import (
    SCHEMA_VERSION,
    Answer,
    CategoryAnswer,
    NumericAnswer,
    PressureUnit,
    PublicTask,
    Scene,
    Skill,
)

QuestionKind = Literal[
    "read_inlet",
    "read_outlet",
    "convert_outlet",
    "compare_outlets",
    "pressure_difference",
    "operating_state",
    "alarm_consistency",
]


@dataclass(frozen=True)
class QuestionDraft:
    public: PublicTask
    answer: Answer
    skill: Skill
    tolerance_milli: int | None = None


class AmbiguousQuestion(ValueError):
    """The provided visible evidence does not uniquely determine the answer."""


def _numeric_schema(units: list[PressureUnit]) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["kind", "value_milli", "unit"],
        "properties": {
            "kind": {"type": "string", "enum": ["numeric"]},
            "value_milli": {"type": "integer"},
            "unit": {"type": "string", "enum": units},
        },
    }


def _category_schema(choices: list[str]) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["kind", "value"],
        "properties": {
            "kind": {"type": "string", "enum": ["category"]},
            "value": {"type": "string", "enum": choices},
        },
    }


def build_question(
    scene: Scene,
    equipment_id: str,
    kind: QuestionKind,
    *,
    task_id: str,
    image_path: str,
    uncertainty_milli_kpa: int = 0,
    target_unit: PressureUnit = "kPa",
    tolerance_milli: int = 0,
) -> QuestionDraft:
    """Create a task from known readings, using the supplied visible reading margin."""
    if uncertainty_milli_kpa < 0 or tolerance_milli < 0:
        raise ValueError("uncertainty and tolerance must be nonnegative")
    pump = next(
        (instrument for instrument in scene.equipment if instrument.id == equipment_id), None
    )
    if pump is None:
        raise ValueError("unknown equipment ID")

    label = f"“{pump.label}”"
    result = PUMP_RULE.solve(pump)
    public_rules = "Use the visible labels, pressure scales and indicators."
    answer: Answer
    skill: Skill
    if kind in ("read_inlet", "read_outlet"):
        position = "inlet" if kind == "read_inlet" else "outlet"
        reading = pump.inlet if kind == "read_inlet" else pump.outlet
        question = (
            f"What pressure does the {position} gauge show for {label}, in the displayed unit?"
        )
        answer = NumericAnswer(kind="numeric", **reading.model_dump())
        skill = "reading"
    elif kind == "convert_outlet":
        if target_unit == pump.outlet.unit:
            raise ValueError("conversion target must differ from the visible source unit")
        question = f"What is the outlet pressure of {label} converted to {target_unit}?"
        public_rules = (
            f"{conversion_rules_text()} Round the answer "
            "to the nearest 0.001 of the requested unit with ties away from zero."
        )
        answer = NumericAnswer(
            kind="numeric", unit=target_unit, value_milli=convert_pressure(pump.outlet, target_unit)
        )
        skill = "conversion"
    elif kind == "pressure_difference":
        question = f"For {label}, what is outlet pressure minus inlet pressure, in kPa?"
        public_rules = (
            f"{conversion_rules_text()} After converting each "
            "reading, round to the nearest 0.001 kPa with ties away from zero."
        )
        answer = NumericAnswer(kind="numeric", unit="kPa", value_milli=result.delta_milli_kpa)
        skill = "difference"
    elif kind == "compare_outlets":
        if len(scene.equipment) != 2:
            raise AmbiguousQuestion("association requires two visibly labeled pumps")
        first, second = scene.equipment
        delta = convert_pressure(first.outlet, "kPa") - convert_pressure(second.outlet, "kPa")
        if abs(delta) <= uncertainty_milli_kpa:
            raise AmbiguousQuestion("outlet readings overlap within the supplied uncertainty")
        winner = first if delta > 0 else second
        question = "Which named pump has the higher outlet pressure after converting to kPa?"
        public_rules = (
            f"{conversion_rules_text()} Round each converted reading to the nearest "
            "0.001 kPa with ties away from zero."
        )
        choices = sorted([first.label, second.label])
        answer = CategoryAnswer(kind="category", value=winner.label)
        skill = "association"
    elif kind in ("operating_state", "alarm_consistency"):
        if not PUMP_RULE.has_unique_state(pump, uncertainty_milli_kpa):
            raise AmbiguousQuestion("reading uncertainty spans the pressure threshold")
        public_rules = PUMP_RULE.public_text
        if kind == "operating_state":
            question = (
                f"What operating state follows from the readings and RUN indicator for {label}?"
            )
            choices = ["STOPPED", "NORMAL", "LOW_PRESSURE"]
            answer = CategoryAnswer(kind="category", value=result.state)
            skill = "operational_state"
        else:
            question = f"Does the displayed ALARM indicator for {label} agree with the public rule?"
            choices = ["CONSISTENT", "CONTRADICTION"]
            answer = CategoryAnswer(kind="category", value=result.consistency)
            skill = "indicator_consistency"
    else:
        raise ValueError("unknown question kind")

    if answer.kind == "numeric":
        question += " Return the value in thousandths of the requested or displayed unit."
        response_schema = _numeric_schema(
            ["bar", "kPa", "psi"] if skill == "reading" else [answer.unit]
        )
    else:
        response_schema = _category_schema(choices)
    return QuestionDraft(
        public=PublicTask(
            schema_version=SCHEMA_VERSION,
            task_id=task_id,
            image_path=image_path,
            question=question,
            public_rules=public_rules,
            response_schema=response_schema,
        ),
        answer=answer,
        skill=skill,
        tolerance_milli=tolerance_milli if answer.kind == "numeric" else None,
    )
