"""Versioned records exchanged between the evaluator, workers, and web client."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, JsonValue, model_validator

SCHEMA_VERSION = "1.0.0"
MAX_SAFE_INTEGER = 9_007_199_254_740_991
ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$"
IMAGE_PATTERN = r"^images/[A-Za-z0-9][A-Za-z0-9_-]{0,79}\.png$"
SHA256_PATTERN = r"^[a-f0-9]{64}$"
TIMESTAMP_PATTERN = (
    r"^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])T"
    r"([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](\.[0-9]{1,6})?"
    r"(Z|[+-]([01][0-9]|2[0-3]):[0-5][0-9])$"
)

SchemaVersion = Literal["1.0.0"]
Identifier = Annotated[str, Field(pattern=ID_PATTERN)]
ImagePath = Annotated[str, Field(pattern=IMAGE_PATTERN)]
Sha256 = Annotated[str, Field(pattern=SHA256_PATTERN)]
SafeInteger = Annotated[int, Field(ge=-MAX_SAFE_INTEGER, le=MAX_SAFE_INTEGER)]
NonNegativeInteger = Annotated[int, Field(ge=0, le=MAX_SAFE_INTEGER)]
PositiveInteger = Annotated[int, Field(ge=1, le=MAX_SAFE_INTEGER)]
NonNegativeNumber = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Label = Annotated[str, Field(min_length=1, max_length=160)]
Text = Annotated[str, Field(min_length=1, max_length=4096)]
PressureUnit = Literal["kPa", "bar", "psi"]
Condition = Literal["C0", "C1", "C2", "C3", "C4"]
AttemptStatus = Literal[
    "correct", "incorrect", "unscored", "invalid_response", "provider_error", "skipped"
]
Split = Literal["dev", "test_frozen", "diagnostic_abstain", "real_slice"]
Skill = Literal[
    "reading",
    "conversion",
    "association",
    "difference",
    "operational_state",
    "indicator_consistency",
]
VariantKind = Literal[
    "original", "semantic", "semantic_preserve", "nonsemantic", "evidence_removed"
]
ValidationStatus = Literal["pending", "accepted", "rejected"]
ANSWERED_STATUSES = ("correct", "incorrect", "unscored")


def _check_timestamp(value: str) -> str:
    datetime.fromisoformat(value)
    return value


Timestamp = Annotated[
    str,
    Field(pattern=TIMESTAMP_PATTERN, json_schema_extra={"format": "date-time"}),
    AfterValidator(_check_timestamp),
]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class VersionedRecord(ContractModel):
    schema_version: SchemaVersion


class Pressure(ContractModel):
    value_milli: SafeInteger
    unit: PressureUnit


class Pump(ContractModel):
    id: Identifier
    label: Label
    inlet: Pressure
    outlet: Pressure
    run: bool
    alarm: bool


class Scene(VersionedRecord):
    base_scene_id: Identifier
    seed: NonNegativeInteger
    layout_family: Identifier
    style_family: Identifier
    equipment: Annotated[list[Pump], Field(min_length=1, max_length=2)]

    @model_validator(mode="after")
    def require_unique_equipment(self) -> Self:
        if len({pump.id for pump in self.equipment}) != len(self.equipment):
            raise ValueError("pump IDs must be unique within a scene")
        if len({pump.label for pump in self.equipment}) != len(self.equipment):
            raise ValueError("pump labels must be unique within a scene")
        return self


class CategoryAnswer(ContractModel):
    kind: Literal["category"]
    value: Label


class NumericAnswer(Pressure):
    kind: Literal["numeric"]


class SetAnswer(ContractModel):
    kind: Literal["set"]
    values: Annotated[list[Label], Field(max_length=32, json_schema_extra={"uniqueItems": True})]

    @model_validator(mode="after")
    def require_unique_values(self) -> Self:
        if len(set(self.values)) != len(self.values):
            raise ValueError("set answer values must be unique")
        return self


Answer = Annotated[CategoryAnswer | NumericAnswer | SetAnswer, Field(discriminator="kind")]


class PublicTask(VersionedRecord):
    task_id: Identifier
    image_path: ImagePath
    question: Text
    public_rules: Text
    response_schema: dict[str, JsonValue]


class EvidenceRegion(ContractModel):
    instrument_id: Identifier
    x: NonNegativeInteger
    y: NonNegativeInteger
    width: PositiveInteger
    height: PositiveInteger


class PrivateTask(VersionedRecord):
    task_id: Identifier
    base_scene_id: Identifier
    group_id: Identifier
    variant_kind: VariantKind
    split: Split
    skill: Skill
    difficulty: dict[str, JsonValue]
    answer: Answer
    tolerance_milli: NonNegativeInteger | None = None
    evidence_regions: list[EvidenceRegion] | None = None
    solver_version: Label
    image_sha256: Sha256
    validation_status: ValidationStatus

    @model_validator(mode="after")
    def check_diagnostic_and_tolerance(self) -> Self:
        if self.tolerance_milli is not None and self.answer.kind != "numeric":
            raise ValueError("only numeric answers may define a tolerance")
        if self.variant_kind == "evidence_removed" and self.split != "diagnostic_abstain":
            raise ValueError("evidence-removed variants belong to the abstention split")
        return self

    def verify_image(self, image: bytes) -> None:
        """Check image integrity after loading bytes through the artifact store."""
        if hashlib.sha256(image).hexdigest() != self.image_sha256:
            raise ValueError("image bytes do not match image_sha256")


class Attempt(VersionedRecord):
    task_id: Identifier
    run_id: Identifier
    model_id: Label
    provider: Label
    condition: Condition
    timestamp: Timestamp
    latency_ms: NonNegativeInteger
    status: AttemptStatus
    model_revision: Label | None = None
    raw_output: str | None = None
    parsed_answer: Answer | None = None
    error: str | None = None
    input_tokens: NonNegativeInteger | None = None
    output_tokens: NonNegativeInteger | None = None
    cost_usd: NonNegativeNumber | None = None
    cached: bool | None = None

    @model_validator(mode="after")
    def check_answer_status(self) -> Self:
        if (self.status in ANSWERED_STATUSES) != (self.parsed_answer is not None):
            raise ValueError("only scored or unscored answers carry parsed_answer")
        return self


class Resolution(ContractModel):
    width: PositiveInteger
    height: PositiveInteger


class Run(VersionedRecord):
    run_id: Identifier
    model_id: Label
    provider: Label
    condition: Condition
    prompt_version: Label
    seed: NonNegativeInteger
    max_calls: NonNegativeInteger
    selected_task_ids_sha256: Sha256
    environment_fingerprint: Text
    demo_only: bool
    model_revision: Label | None = None
    resolution: Resolution | None = None
    sampling_parameters: dict[str, JsonValue] | None = None
    max_cost_usd: NonNegativeNumber | None = None


SCHEMA_MODELS = {
    "scene": Scene,
    "task_public": PublicTask,
    "task_private": PrivateTask,
    "attempt": Attempt,
    "run": Run,
}


def export_json_schemas(directory: Path) -> None:
    """Write Draft 2020-12 schemas for consumers outside Python."""
    directory.mkdir(parents=True, exist_ok=True)
    for name, model in SCHEMA_MODELS.items():
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            **model.model_json_schema(),
        }
        if model is Attempt:
            schema["if"] = {"properties": {"status": {"enum": list(ANSWERED_STATUSES)}}}
            schema["then"] = {
                "required": ["parsed_answer"],
                "properties": {"parsed_answer": {"type": "object"}},
            }
            schema["else"] = {"properties": {"parsed_answer": {"type": "null"}}}
        if model is PrivateTask:
            schema["allOf"] = [
                {
                    "if": {"properties": {"variant_kind": {"const": "evidence_removed"}}},
                    "then": {"properties": {"split": {"const": "diagnostic_abstain"}}},
                },
                {
                    "if": {
                        "properties": {"answer": {"properties": {"kind": {"const": "numeric"}}}}
                    },
                    "else": {"properties": {"tolerance_milli": {"type": "null"}}},
                },
            ]
        path = directory / f"{name}.schema.json"
        path.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    export_json_schemas(Path("schemas"))
