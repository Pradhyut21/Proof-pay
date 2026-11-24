"""Question templates and deterministic references (INTERIM shim for #6).

Skills: R reading, C conversion, M composition (state / pressure difference), X consistency.
Every answer is derived from the scene truth with fixed-point arithmetic; tolerances are one
minor tick (readings) or the composed minor ticks (differences).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .interim_rules import expected_alarm
from .scene import Scene
from .units import convert_milli, from_milli_kpa

UNIT_ORDER = ("kPa", "bar", "psi")
STATES = ["STOPPED", "NORMAL", "LOW_PRESSURE"]
CONSISTENCY = ["CONSISTENT", "INCONSISTENT"]


@dataclass
class Question:
    skill: str  # R | C | M | X
    kind: str  # read | convert | state | delta | consistency
    pump_id: str
    role: str | None
    target_unit: str | None
    text: str
    answer: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def numeric(value_milli: int, unit: str, tol_milli: int) -> dict[str, Any]:
    return {"kind": "numeric", "value_milli": value_milli, "unit": unit, "tolerance_milli": tol_milli}


def category(value: str) -> dict[str, Any]:
    return {"kind": "category", "value": value}


def build_questions(scene: Scene) -> list[Question]:
    out: list[Question] = []
    for p in scene.pumps:
        for role in ("INLET", "OUTLET"):
            g = p.gauge(role)
            out.append(
                Question(
                    "R",
                    "read",
                    p.pump_id,
                    role,
                    g.unit,
                    f"What does the {role} pressure gauge of {p.label} read? "
                    "Answer as a number in the unit shown on that gauge.",
                    numeric(g.value_milli, g.unit, g.minor_milli),
                )
            )
            tgt = "bar" if g.unit != "bar" else "kPa"
            out.append(
                Question(
                    "C",
                    "convert",
                    p.pump_id,
                    role,
                    tgt,
                    f"Read the {role} pressure gauge of {p.label} and give its value in {tgt}.",
                    numeric(
                        convert_milli(g.value_milli, g.unit, tgt),
                        tgt,
                        max(1, convert_milli(g.minor_milli, g.unit, tgt)),
                    ),
                )
            )
        out.append(
            Question(
                "M",
                "state",
                p.pump_id,
                None,
                None,
                f"Using the public rules, what is the operating state of {p.label}?",
                category(p.state()),
            )
        )
        gi, go = p.gauge("INLET"), p.gauge("OUTLET")
        out.append(
            Question(
                "M",
                "delta",
                p.pump_id,
                None,
                "kPa",
                f"What is the outlet minus inlet pressure of {p.label}, in kPa?",
                numeric(
                    from_milli_kpa(p.delta_mkpa(), "kPa"), "kPa", from_milli_kpa(gi.minor_mkpa + go.minor_mkpa, "kPa")
                ),
            )
        )
        out.append(
            Question(
                "X",
                "consistency",
                p.pump_id,
                None,
                None,
                f"Is the ALARM indicator of {p.label} consistent with the public rules? "
                "Answer CONSISTENT or INCONSISTENT.",
                category("CONSISTENT" if p.alarm == expected_alarm(p.state()) else "INCONSISTENT"),
            )
        )
    return out


def response_schema(q: Question, diagnostic: bool = False) -> dict[str, Any]:
    if q.kind == "state":
        enum = STATES + (["INSUFFICIENT"] if diagnostic else [])
        return {"type": "category", "allowed": enum}
    if q.kind == "consistency":
        return {"type": "category", "allowed": CONSISTENCY}
    unit = q.target_unit
    return {"type": "numeric", "unit": unit, "scale": "milli", "note": "value_milli is thousandths of the stated unit"}


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
        return category("CONSISTENT" if d["alarm_consistent"] else "INCONSISTENT")
    return None


def answers_agree(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if a["kind"] == "category":
        return a["value"] == b["value"]
    return a["unit"] == b["unit"] and abs(a["value_milli"] - b["value_milli"]) <= a["tolerance_milli"]
