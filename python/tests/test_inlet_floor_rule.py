from dataclasses import replace

import pytest
from manual_panel import panel, png

from panelproof.question_bridge import answer_from_trace, build_questions, category
from panelproof.questions import AmbiguousQuestion, build_question
from panelproof.rules import INLET_FLOOR_RULE, PUMP_RULE, convert_pressure
from panelproof.scene import generate_scene, load_config
from panelproof.schemas import Pressure, Pump, Scene
from panelproof.verify import verify_png


def pump(inlet_milli, unit="kPa", *, run=True, alarm=False):
    return Pump(
        id="A",
        label="PUMP A",
        inlet=Pressure(value_milli=inlet_milli, unit=unit),
        outlet=Pressure(value_milli=460_000, unit="kPa"),
        run=run,
        alarm=alarm,
    )


def contract(pump_record):
    return Scene(
        schema_version="1.0.0",
        base_scene_id="scene-floor",
        seed=42,
        layout_family="1p-single",
        style_family="daylight",
        equipment=[pump_record],
    )


def draft(scene, kind="inlet_state", uncertainty=0):
    return build_question(
        scene,
        "A",
        kind,
        task_id="floor-question",
        image_path="images/floor-question.png",
        uncertainty_milli_kpa=uncertainty,
    )


@pytest.mark.parametrize(
    ("inlet_milli", "unit", "run", "alarm", "state", "consistency"),
    [
        (149_999, "kPa", True, True, "LOW_PRESSURE", "CONSISTENT"),
        (150_000, "kPa", True, False, "NORMAL", "CONSISTENT"),
        (150_000, "kPa", True, True, "NORMAL", "CONTRADICTION"),
        (1_500, "bar", True, False, "NORMAL", "CONSISTENT"),
        (21_000, "psi", True, False, "LOW_PRESSURE", "CONTRADICTION"),
        (22_000, "psi", True, False, "NORMAL", "CONSISTENT"),
        (100_000, "kPa", False, False, "STOPPED", "CONSISTENT"),
        (200_000, "kPa", False, True, "STOPPED", "CONTRADICTION"),
    ],
)
def test_inlet_floor_boundaries_and_alarm_expectation(
    inlet_milli, unit, run, alarm, state, consistency
):
    record = pump(inlet_milli, unit, run=run, alarm=alarm)
    result = INLET_FLOOR_RULE.solve(record)
    assert result.state == state
    assert result.consistency == consistency
    assert result.inlet_milli_kpa == convert_pressure(record.inlet, "kPa")
    assert result.outlet_milli_kpa == 460_000
    assert result.delta_milli_kpa == result.outlet_milli_kpa - result.inlet_milli_kpa


def test_public_question_specifies_the_inlet_rule_independently_of_the_delta_rule():
    record = pump(200_000)
    scene = contract(record)
    inlet = draft(scene)
    legacy = draft(scene, "operating_state")

    assert inlet.skill == "operational_state"
    assert "inlet-pressure rule" in inlet.public.question
    assert "150 kPa" in inlet.public.public_rules
    assert "300 kPa" not in inlet.public.public_rules
    assert "Round it to the nearest 0.001 kPa" in inlet.public.public_rules
    assert set(inlet.public.response_schema["properties"]["value"]["enum"]) == {
        "STOPPED",
        "NORMAL",
        "LOW_PRESSURE",
    }
    assert inlet.answer.value == "NORMAL"
    assert legacy.answer.value == PUMP_RULE.solve(record).state == "LOW_PRESSURE"


def test_inlet_uncertainty_boundary_is_inclusive_and_stopped_is_unambiguous():
    assert draft(contract(pump(160_000)), uncertainty=10_000).answer.value == "NORMAL"
    assert draft(contract(pump(139_999)), uncertainty=10_000).answer.value == "LOW_PRESSURE"
    assert draft(contract(pump(150_000, run=False)), uncertainty=10_000).answer.value == "STOPPED"
    with pytest.raises(AmbiguousQuestion, match="inlet-pressure threshold"):
        draft(contract(pump(140_000)), uncertainty=10_000)


def test_generated_question_addition_is_opt_in_and_skips_ambiguous_inlet():
    cfg = load_config() | {
        "pumps": {"min": 1, "max": 1},
        "unit_weights": {"kPa": 1.0},
    }
    scene = generate_scene("inlet-rule-bridge", cfg)
    only = scene.pumps[0]
    inlet = only.gauge("INLET")
    only.run = True
    inlet.value_milli = 150_000
    assert build_questions(scene, include_inlet_floor=True) == build_questions(scene)

    inlet.value_milli = 200_000
    legacy = build_questions(scene)
    expanded = build_questions(scene, include_inlet_floor=True)
    assert [q for q in expanded if q.kind != "inlet_state"] == legacy
    new = next(q for q in expanded if q.kind == "inlet_state")
    assert new.pump_id == "A"
    assert (new.skill, new.contract_skill, new.role) == ("M", "operational_state", "INLET")
    assert new.answer == category("NORMAL")


@pytest.fixture
def inlet_question():
    cfg = load_config() | {
        "pumps": {"min": 1, "max": 1},
        "unit_weights": {"kPa": 1.0},
    }
    scene = generate_scene("inlet-rule-independent-trace", cfg)
    scene.pumps[0].run = True
    scene.pumps[0].gauge("INLET").value_milli = 200_000
    scene.pumps[0].gauge("OUTLET").value_milli = 460_000
    return next(
        q for q in build_questions(scene, include_inlet_floor=True) if q.kind == "inlet_state"
    )


def test_real_raster_answer_uses_recovered_inlet_not_the_delta_verdict(inlet_question):
    trace = verify_png(png(panel(inlet_tick=10, outlet_tick=23)))["pumps"][0]
    assert trace["verdict"] == "verified"
    assert trace["derived"]["state"] == "LOW_PRESSURE"
    assert trace["gauges"]["INLET"]["reading_mkpa"] == 200_000
    assert answer_from_trace(inlet_question, trace) == inlet_question.answer == category("NORMAL")
    misleading_reference = replace(inlet_question, answer=category("STOPPED"))
    assert answer_from_trace(misleading_reference, trace) == category("NORMAL")


def test_trace_must_recover_the_relevant_evidence_and_clear_the_inlet_threshold(inlet_question):
    trace = {
        "verdict": "verified",
        "run": True,
        "gauges": {"INLET": {"reading_mkpa": 150_000, "uncertainty_mkpa": 10_000}},
    }
    assert answer_from_trace(inlet_question, trace) is None
    assert answer_from_trace(inlet_question, trace | {"gauges": {}}) is None
    assert answer_from_trace(inlet_question, trace | {"verdict": "rejected"}) is None
    assert answer_from_trace(inlet_question, trace | {"run": None}) is None
    assert answer_from_trace(inlet_question, trace | {"run": False, "gauges": {}}) == category(
        "STOPPED"
    )
