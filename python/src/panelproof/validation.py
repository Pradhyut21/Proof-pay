"""Validate candidate artifacts and summarize evidence without running a generator or model."""

from __future__ import annotations

import hashlib
import io
import struct
import zlib
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import asdict, dataclass
from typing import Literal

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from PIL import Image
from pydantic import ValidationError
from referencing import Registry
from referencing.exceptions import Unresolvable

from .rules import convert_pressure
from .schemas import Answer, EvidenceRegion, Pressure, PrivateTask, PublicTask, ValidationStatus

CheckStatus = Literal["pass", "fail", "pending"]
RasterOutcome = Literal["verified", "unreadable", "unsupported"]
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PIXEL_CHUNKS = frozenset({b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS"})
ANIMATION_CHUNKS = frozenset({b"acTL", b"fcTL", b"fdAT"})
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_DIMENSION = 4096


@dataclass(frozen=True)
class AnswerabilityEvidence:
    unique: bool
    margin_required: bool = True
    observed_margin_milli_kpa: int | None = None
    required_margin_milli_kpa: int | None = None


@dataclass(frozen=True)
class RasterEvidence:
    task_id: str
    image_sha256: str
    verifier_version: str
    outcome: RasterOutcome
    recovered_answer: Answer | None = None
    observed_regions: tuple[EvidenceRegion, ...] = ()


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: CheckStatus
    reason: str


@dataclass(frozen=True)
class CandidateReport:
    task_id: str | None
    skill: str | None
    status: ValidationStatus
    image_sha256: str | None
    checks: tuple[CheckResult, ...]

    def to_dict(self) -> dict[str, object]:
        """Serialize metadata and reason codes for the internal validation report."""
        return asdict(self)


def _check(name: str, passed: bool, passed_reason: str, failed_reason: str) -> CheckResult:
    if passed:
        return CheckResult(name, "pass", passed_reason)
    return CheckResult(name, "fail", failed_reason)


def _png_chunks(image: bytes) -> Iterator[tuple[bytes, memoryview]]:
    if not image.startswith(PNG_SIGNATURE):
        raise ValueError("invalid_png_signature")
    data = memoryview(image)
    offset = len(PNG_SIGNATURE)
    index = 0
    has_image_data = False
    image_data_ended = False
    while offset + 12 <= len(data):
        length, kind = struct.unpack_from(">I4s", data, offset)
        end = offset + 12 + length
        if end > len(data):
            raise ValueError("truncated_png_chunk")
        chunk = data[offset + 8 : end - 4]
        crc = struct.unpack_from(">I", data, end - 4)[0]
        if zlib.crc32(chunk, zlib.crc32(kind)) != crc:
            raise ValueError("png_chunk_crc_mismatch")
        if (index == 0) != (kind == b"IHDR") or (kind == b"IHDR" and length != 13):
            raise ValueError("invalid_png_header")
        if kind == b"IDAT":
            if image_data_ended:
                raise ValueError("noncontiguous_png_image_data")
            has_image_data = True
        elif has_image_data:
            image_data_ended = True
        if kind == b"IEND" and (length or end != len(data) or not has_image_data):
            raise ValueError("invalid_png_end")

        yield kind, chunk
        if kind == b"IEND":
            return
        offset = end
        index += 1
    raise ValueError("missing_png_end")


def _inspect_image(
    image: bytes | None, expected_size: tuple[int, int] | None
) -> tuple[list[CheckResult], tuple[int, int] | None]:
    if image is None:
        return [
            CheckResult(name, "pending", "image_bytes_missing")
            for name in ("png_container", "image_dimensions", "png_metadata")
        ], None
    if len(image) > MAX_IMAGE_BYTES:
        return [
            CheckResult("png_container", "fail", "image_byte_limit_exceeded"),
            CheckResult("image_dimensions", "pending", "image_inspection_blocked"),
            CheckResult("png_metadata", "pending", "image_inspection_blocked"),
        ], None

    size = None
    extra_chunks: set[bytes] = set()
    try:
        for kind, chunk in _png_chunks(image):
            if kind == b"IHDR":
                size = struct.unpack(">II", chunk[:8])
            if kind not in PIXEL_CHUNKS:
                extra_chunks.add(kind)
    except ValueError as error:
        return [
            CheckResult("png_container", "fail", str(error)),
            CheckResult("image_dimensions", "pending", "image_inspection_blocked"),
            CheckResult("png_metadata", "pending", "image_inspection_blocked"),
        ], None

    assert size is not None
    dimensions_ok = all(0 < dimension <= MAX_IMAGE_DIMENSION for dimension in size)
    dimensions = _check(
        "image_dimensions",
        dimensions_ok and (expected_size is None or size == expected_size),
        "image_dimensions_valid",
        "image_dimensions_out_of_bounds" if not dimensions_ok else "unexpected_image_dimensions",
    )
    metadata = _check(
        "png_metadata",
        not extra_chunks,
        "png_contains_only_pixel_chunks",
        "animated_png" if extra_chunks & ANIMATION_CHUNKS else "non_pixel_png_chunks",
    )
    if not dimensions_ok or extra_chunks:
        container = CheckResult("png_container", "pending", "image_decode_blocked")
    else:
        try:
            with Image.open(io.BytesIO(image), formats=["PNG"]) as panel:
                panel.load()
        except (OSError, SyntaxError, ValueError, Image.DecompressionBombError):
            container = CheckResult("png_container", "fail", "png_decode_error")
        else:
            container = CheckResult("png_container", "pass", "png_chunks_and_pixels_valid")
    return [container, dimensions, metadata], size if dimensions_ok else None


def _matches_answer(observed: Answer, private: PrivateTask) -> bool:
    expected = private.answer
    if observed.kind == "numeric" and expected.kind == "numeric":
        pressure = Pressure(value_milli=observed.value_milli, unit=observed.unit)
        delta = convert_pressure(pressure, expected.unit) - expected.value_milli
        return abs(delta) <= (private.tolerance_milli or 0)
    if observed.kind == "set" and expected.kind == "set":
        return set(observed.values) == set(expected.values)
    return observed == expected


def _check_response_schema(public: PublicTask | None, private: PrivateTask | None) -> CheckResult:
    name = "response_schema"
    if public is None or private is None:
        return CheckResult(name, "pending", "valid_task_records_missing")
    schema = public.response_schema
    try:
        Draft202012Validator.check_schema(schema)
        valid = Draft202012Validator(schema, registry=Registry()).is_valid(
            private.answer.model_dump(mode="json")
        )
    except (SchemaError, Unresolvable):
        return CheckResult(name, "fail", "invalid_or_unresolved_response_schema")
    return _check(name, valid, "reference_matches_response_schema", "reference_rejected_by_schema")


def _check_answerability(evidence: AnswerabilityEvidence | None) -> CheckResult:
    name = "answerability"
    if evidence is None:
        return CheckResult(name, "pending", "answerability_evidence_missing")
    if not evidence.unique:
        return CheckResult(name, "fail", "answer_is_ambiguous")

    observed = evidence.observed_margin_milli_kpa
    required = evidence.required_margin_milli_kpa
    if not evidence.margin_required:
        return _check(
            name,
            observed is None and required is None,
            "unique_answer_margin_not_applicable",
            "unexpected_answer_margin",
        )
    if required is None or observed is None:
        return CheckResult(name, "pending", "answer_margin_evidence_missing")
    if required < 0 or observed < 0:
        return CheckResult(name, "fail", "invalid_answer_margin")
    return _check(
        name, observed >= required, "answer_margin_sufficient", "insufficient_answer_margin"
    )


def _check_raster(
    evidence: RasterEvidence | None, private: PrivateTask | None, digest: str | None
) -> CheckResult:
    name = "raster_agreement"
    if evidence is None:
        return CheckResult(name, "pending", "independent_raster_evidence_missing")
    if private is None or digest is None:
        return CheckResult(name, "pending", "valid_task_and_image_required")
    if evidence.task_id != private.task_id or evidence.image_sha256 != digest:
        return CheckResult(name, "fail", "raster_trace_provenance_mismatch")
    if evidence.outcome != "verified":
        return CheckResult(name, "fail", "raster_evidence_unreadable_or_unsupported")
    if not evidence.verifier_version.strip() or evidence.recovered_answer is None:
        return CheckResult(name, "fail", "raster_trace_incomplete")
    return _check(
        name,
        _matches_answer(evidence.recovered_answer, private),
        "raster_answer_matches_reference",
        "raster_answer_disagrees_with_reference",
    )


def _check_evidence_bounds(
    raster: RasterEvidence | None, private: PrivateTask | None, size: tuple[int, int] | None
) -> CheckResult:
    name = "evidence_bounds"
    if size is None or raster is None or private is None:
        return CheckResult(name, "pending", "image_dimensions_or_evidence_missing")
    if not raster.observed_regions:
        return CheckResult(name, "fail", "raster_regions_missing")
    width, height = size
    regions = (*raster.observed_regions, *(private.evidence_regions or ()))
    return _check(
        name,
        all(
            0 <= region.x < region.x + region.width <= width
            and 0 <= region.y < region.y + region.height <= height
            for region in regions
        ),
        "evidence_regions_inside_image",
        "evidence_region_out_of_bounds",
    )


def validate_candidate(
    public: PublicTask | Mapping[str, object] | None,
    private: PrivateTask | Mapping[str, object] | None,
    *,
    image: bytes | None = None,
    repeated_image: bytes | None = None,
    expected_size: tuple[int, int] | None = None,
    answerability: AnswerabilityEvidence | None = None,
    raster: RasterEvidence | None = None,
    secondary_answer: Answer | None = None,
) -> CandidateReport:
    """Check a candidate and independently supplied evidence without side effects."""
    checks: list[CheckResult] = []
    public_task = None
    if public is None:
        checks.append(CheckResult("public_schema", "pending", "public_task_missing"))
    else:
        try:
            public_record = public.model_dump() if isinstance(public, PublicTask) else public
            public_task = PublicTask.model_validate(public_record)
        except ValidationError:
            checks.append(CheckResult("public_schema", "fail", "invalid_public_task"))
        else:
            checks.append(CheckResult("public_schema", "pass", "public_task_valid"))

    private_task = None
    if private is None:
        checks.append(CheckResult("private_schema", "pending", "private_task_missing"))
    else:
        try:
            private_record = private.model_dump() if isinstance(private, PrivateTask) else private
            private_task = PrivateTask.model_validate(private_record)
        except ValidationError:
            checks.append(CheckResult("private_schema", "fail", "invalid_private_task"))
        else:
            checks.append(CheckResult("private_schema", "pass", "private_task_valid"))

    if public_task is None or private_task is None:
        checks.append(CheckResult("task_identity", "pending", "valid_task_records_missing"))
    else:
        checks.append(
            _check(
                "task_identity",
                public_task.task_id == private_task.task_id,
                "public_private_task_ids_match",
                "public_private_task_ids_differ",
            )
        )

    checks.append(_check_response_schema(public_task, private_task))
    image_checks, size = _inspect_image(image, expected_size)
    checks.extend(image_checks)
    digest = (
        hashlib.sha256(image).hexdigest()
        if image is not None and len(image) <= MAX_IMAGE_BYTES
        else None
    )
    if digest is None or private_task is None:
        checks.append(CheckResult("image_hash", "pending", "valid_private_task_and_image_required"))
    else:
        checks.append(
            _check(
                "image_hash",
                digest == private_task.image_sha256,
                "image_sha256_matches_reference",
                "image_sha256_mismatch",
            )
        )
    if repeated_image is not None and len(repeated_image) > MAX_IMAGE_BYTES:
        checks.append(CheckResult("repeatability", "fail", "repeat_render_byte_limit_exceeded"))
    elif digest is None or repeated_image is None:
        checks.append(CheckResult("repeatability", "pending", "repeat_render_missing"))
    else:
        checks.append(
            _check(
                "repeatability",
                hashlib.sha256(repeated_image).hexdigest() == digest,
                "repeat_render_sha256_matches",
                "repeat_render_sha256_mismatch",
            )
        )
    checks.append(_check_evidence_bounds(raster, private_task, size))
    checks.append(_check_answerability(answerability))
    checks.append(_check_raster(raster, private_task, digest))
    if secondary_answer is None or private_task is None:
        checks.append(CheckResult("reference_parity", "pending", "secondary_rule_evidence_missing"))
    else:
        checks.append(
            _check(
                "reference_parity",
                _matches_answer(secondary_answer, private_task),
                "secondary_rule_answer_matches",
                "secondary_rule_answer_disagrees",
            )
        )

    status: ValidationStatus = "accepted"
    check_states = {check.status for check in checks}
    if "fail" in check_states:
        status = "rejected"
    elif "pending" in check_states:
        status = "pending"
    task_id = (
        public_task.task_id
        if public_task is not None
        else private_task.task_id
        if private_task is not None
        else None
    )
    return CandidateReport(
        task_id=task_id,
        skill=private_task.skill if private_task is not None else None,
        status=status,
        image_sha256=digest,
        checks=tuple(checks),
    )


def summarize_reports(reports: Iterable[CandidateReport]) -> dict[str, object]:
    """Count accepted, pending and rejected candidates, plus each check's reasons."""
    statuses: Counter[str] = Counter({"accepted": 0, "pending": 0, "rejected": 0})
    check_statuses: dict[str, Counter[str]] = {}
    check_reasons: dict[str, Counter[str]] = {}
    skills: dict[str, Counter[str]] = {}
    for report in reports:
        statuses[report.status] += 1
        skill_counts = skills.setdefault(
            report.skill or "unknown", Counter({"accepted": 0, "pending": 0, "rejected": 0})
        )
        skill_counts[report.status] += 1
        for check in report.checks:
            counts = check_statuses.setdefault(
                check.name, Counter({"pass": 0, "fail": 0, "pending": 0})
            )
            counts[check.status] += 1
            check_reasons.setdefault(check.name, Counter())[check.reason] += 1
    return {
        "candidate_count": statuses.total(),
        "status_counts": dict(statuses),
        "skill_status_counts": {name: dict(counts) for name, counts in sorted(skills.items())},
        "check_counts": {
            name: {
                "status_counts": dict(counts),
                "reason_counts": dict(sorted(check_reasons[name].items())),
            }
            for name, counts in sorted(check_statuses.items())
        },
    }
