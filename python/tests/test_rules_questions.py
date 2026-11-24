import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from panelproof.balance import audit_alarm_balance
from panelproof.questions import AmbiguousQuestion, build_question
from panelproof.rules import PUMP_RULE, convert_pressure
from panelproof.schemas import Pressure, Pump, Scene

ROOT = Path(__file__).resolve().parents[2]
GOLDENS = json.loads((ROOT / "shared/golden/pump_rules.json").read_text(encoding="utf-8"))


def pump(inlet, outlet, *, run=True, alarm=False, identifier="p1", label="Pump A"):
    return Pump.model_validate(
        {
            "id": identifier,
            "label": label,
            "run": run,
            "alarm": alarm,
            "inlet": {"value_milli": inlet, "unit": "kPa"},
            "outlet": {"value_milli": outlet, "unit": "kPa"},
        }
    )


def scene(*pumps):
    return Scene(
        schema_version="1.0.0",
        base_scene_id="fixture-1",
        seed=1,
        layout_family="grid",
        style_family="slate",
        equipment=list(pumps),
    )


def question(panel, kind, **kwargs):
    return build_question(
        panel, "p1", kind, task_id="task-1", image_path="images/panel-1.png", **kwargs
    )


@pytest.mark.parametrize("case", GOLDENS, ids=[case["id"] for case in GOLDENS])
def test_rule_goldens(case):
    instrument = Pump.model_validate(
        {
            "id": "p1",
            "label": "Pump A",
            "inlet": case["inlet"],
            "outlet": case["outlet"],
            "run": case["run"],
            "alarm": case["alarm"],
        }
    )
    result = PUMP_RULE.solve(instrument)
    assert result.state == case["expected_state"]
    assert result.consistency == case["expected_consistency"]


def test_exact_unit_conversions_and_sign():
    assert convert_pressure(Pressure(value_milli=300_000, unit="kPa"), "bar") == 3_000
    assert convert_pressure(Pressure(value_milli=50, unit="kPa"), "bar") == 1
    assert convert_pressure(Pressure(value_milli=-50, unit="kPa"), "bar") == -1
    assert convert_pressure(Pressure(value_milli=1000, unit="psi"), "kPa") == 6895


def test_public_task_excludes_reference_and_reading_unit_cue():
    task = question(scene(pump(97_000, 420_000)), "read_inlet")
    payload = task.public.model_dump()
    assert set(payload) == {
        "schema_version",
        "task_id",
        "image_path",
        "question",
        "public_rules",
        "response_schema",
    }
    assert "97000" not in task.public.model_dump_json()
    assert set(payload["response_schema"]["properties"]["unit"]["enum"]) == {"kPa", "bar", "psi"}
    Draft202012Validator(task.public.response_schema).validate(task.answer.model_dump())


def test_threshold_uncertainty_and_run_indicator():
    at_threshold = pump(100_000, 400_000)
    assert question(scene(at_threshold), "operating_state").answer.value == "NORMAL"
    with pytest.raises(AmbiguousQuestion, match="spans"):
        question(scene(at_threshold), "operating_state", uncertainty_milli_kpa=5_000)
    stopped = pump(100_000, 400_000, run=False)
    assert question(
        scene(stopped), "operating_state", uncertainty_milli_kpa=5_000
    ).answer.value == ("STOPPED")


def test_association_is_order_independent_and_ties_fail():
    first = pump(100_000, 500_000)
    second = pump(100_000, 600_000, identifier="p2", label="Pump B")
    assert question(scene(first, second), "compare_outlets").answer.value == "Pump B"
    assert question(scene(second, first), "compare_outlets").answer.value == "Pump B"
    with pytest.raises(AmbiguousQuestion, match="overlap"):
        question(scene(first, second), "compare_outlets", uncertainty_milli_kpa=100_000)


def test_balance_audit_detects_independent_and_shortcut_biased_candidates():
    candidates = (
        pump(0, outlet, alarm=alarm)
        for _ in range(250)
        for outlet in (100_000, 500_000)
        for alarm in (False, True)
    )
    balanced = audit_alarm_balance(candidates)
    assert balanced.samples == 1000
    assert set(balanced.expected_displayed.values()) == {250}
    assert balanced.lamp_state_mutual_information == 0
    assert balanced.lamp_consistency_mutual_information == 0
    biased = audit_alarm_balance([pump(0, 100_000, alarm=True), pump(0, 500_000)])
    assert biased.lamp_state_mutual_information == 1
