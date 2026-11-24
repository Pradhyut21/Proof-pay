import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import TypeAdapter, ValidationError

from panelproof.schemas import (
    SCHEMA_MODELS,
    Answer,
    Pressure,
    PrivateTask,
    PublicTask,
    Scene,
    export_json_schemas,
)

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "schemas"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def example(name: str):
    return read_json(SCHEMAS / "examples" / f"{name}.json")


@pytest.mark.parametrize("name", SCHEMA_MODELS)
def test_examples_pass_both_validators(name):
    schema = read_json(SCHEMAS / f"{name}.schema.json")
    Draft202012Validator.check_schema(schema)
    data = example(name)
    Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER).validate(data)

    model = SCHEMA_MODELS[name]
    record = model.model_validate(data)
    assert record.model_dump(mode="json", exclude_unset=True) == data
    assert model.model_validate_json(record.model_dump_json()) == record


def test_generated_schemas_are_current(tmp_path):
    export_json_schemas(tmp_path)
    for name in SCHEMA_MODELS:
        schema_name = f"{name}.schema.json"
        assert read_json(tmp_path / schema_name) == read_json(SCHEMAS / schema_name)


def test_pump_rule_fixture_shape():
    rows = read_json(ROOT / "shared" / "golden" / "pump_rules.json")
    assert len(rows) >= 20
    assert len({row["id"] for row in rows}) == len(rows)
    for row in rows:
        Pressure.model_validate(row["inlet"])
        Pressure.model_validate(row["outlet"])
        assert type(row["run"]) is bool and type(row["alarm"]) is bool
        assert row["expected_state"] in {"STOPPED", "NORMAL", "LOW_PRESSURE"}
        assert row["expected_consistency"] in {"CONSISTENT", "CONTRADICTION"}


@pytest.mark.parametrize(
    "field", ["seed", "answer", "group_id", "evidence_regions", "image_sha256"]
)
def test_public_task_rejects_private_fields(field):
    data = example("task_public")
    data[field] = "unexpected"

    with pytest.raises(ValidationError, match="Extra inputs"):
        PublicTask.model_validate(data)
    assert not Draft202012Validator(read_json(SCHEMAS / "task_public.schema.json")).is_valid(data)


def test_private_task_cannot_be_validated_as_public():
    with pytest.raises(ValidationError):
        PublicTask.model_validate(example("task_private"))


@pytest.mark.parametrize(
    ("name", "changes"),
    [
        ("task_public", {"image_path": "images/../hidden.png"}),
        ("task_public", {"schema_version": "0.9.0"}),
        ("task_private", {"image_sha256": "invalid"}),
        ("task_private", {"split": "unknown"}),
        ("task_private", {"tolerance_milli": 1}),
        ("task_private", {"variant_kind": "evidence_removed"}),
        ("attempt", {"status": "provider_error"}),
        ("attempt", {"parsed_answer": None}),
        ("attempt", {"condition": "C9"}),
        ("attempt", {"timestamp": "2026-13-01T07:00:00Z"}),
        ("run", {"max_calls": -1}),
        ("run", {"resolution": {"width": 0, "height": 10}}),
    ],
)
def test_invalid_records_are_rejected(name, changes):
    record = example(name) | changes
    with pytest.raises(ValidationError):
        SCHEMA_MODELS[name].model_validate(record)
    validator = Draft202012Validator(
        read_json(SCHEMAS / f"{name}.schema.json"),
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )
    assert not validator.is_valid(record)


def test_attempt_timestamp_requires_a_real_calendar_date():
    data = example("attempt") | {"timestamp": "2026-11-31T07:00:00Z"}
    with pytest.raises(ValidationError, match="day is out of range"):
        SCHEMA_MODELS["attempt"].model_validate(data)


@pytest.mark.parametrize(
    "answer",
    [
        {"kind": "numeric", "value_milli": 1000, "unit": "Pa"},
        {"kind": "numeric", "value_milli": "1000", "unit": "kPa"},
        {"kind": "numeric", "value_milli": True, "unit": "kPa"},
        {"kind": "set", "values": ["X", "X"]},
        {"kind": "unsupported", "value": "NORMAL"},
    ],
)
def test_invalid_answer_variants(answer):
    with pytest.raises(ValidationError):
        TypeAdapter(Answer).validate_python(answer)


def test_copied_equipment_id_and_label_are_rejected():
    scene = example("scene")
    pump = scene["equipment"][0]
    scene["equipment"].append(pump.copy())
    with pytest.raises(ValidationError, match="pump IDs must be unique"):
        Scene.model_validate(scene)

    scene["equipment"][1]["id"] = "P2"
    with pytest.raises(ValidationError, match="pump labels must be unique"):
        Scene.model_validate(scene)


def test_image_digest_verifies_actual_bytes():
    task = PrivateTask.model_validate(example("task_private"))
    task.verify_image(b"abc")
    with pytest.raises(ValueError, match="image_sha256"):
        task.verify_image(b"abd")
