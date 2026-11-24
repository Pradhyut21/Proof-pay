import hashlib
import io
import json
import struct
import zlib
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from panelproof import validation
from panelproof.schemas import CategoryAnswer, EvidenceRegion, NumericAnswer
from panelproof.validation import (
    MAX_IMAGE_DIMENSION,
    AnswerabilityEvidence,
    RasterEvidence,
    summarize_reports,
    validate_candidate,
)

EXAMPLES = Path(__file__).resolve().parents[2] / "schemas" / "examples"


def png_bytes(*, width: int = 96, height: int = 64, pnginfo: PngInfo | None = None) -> bytes:
    buffer = io.BytesIO()
    with Image.new("RGB", (width, height), "black") as image:
        image.save(buffer, format="PNG", pnginfo=pnginfo)
    return buffer.getvalue()


@pytest.fixture
def candidate():
    image = png_bytes()
    digest = hashlib.sha256(image).hexdigest()
    public = json.loads((EXAMPLES / "task_public.json").read_text(encoding="utf-8"))
    private = json.loads((EXAMPLES / "task_private.json").read_text(encoding="utf-8"))
    evidence = EvidenceRegion(instrument_id="P1-inlet", x=20, y=16, width=30, height=40)
    answer = CategoryAnswer(kind="category", value="NORMAL")
    private |= {"image_sha256": digest, "evidence_regions": [evidence.model_dump()]}
    return {
        "public": public,
        "private": private,
        "image": image,
        "repeated_image": image,
        "expected_size": (96, 64),
        "answerability": AnswerabilityEvidence(
            unique=True, observed_margin_milli_kpa=20_000, required_margin_milli_kpa=10_000
        ),
        "raster": RasterEvidence(
            task_id=public["task_id"],
            image_sha256=digest,
            verifier_version="fixture-only-raster",
            outcome="verified",
            recovered_answer=answer,
            observed_regions=(evidence,),
        ),
        "secondary_answer": answer,
    }


def get_check(report, name):
    return next(check for check in report.checks if check.name == name)


def test_complete_synthetic_fixture_passes_all_checks(candidate):
    report = validate_candidate(**candidate)
    assert report.status == "accepted"
    assert {check.status for check in report.checks} == {"pass"}
    assert report.image_sha256 == candidate["private"]["image_sha256"]
    assert "answer" not in report.to_dict()
    assert json.loads(json.dumps(report.to_dict()))["status"] == "accepted"


@pytest.mark.parametrize(
    ("overrides", "check", "reason"),
    [
        ({"image": None}, "png_container", "image_bytes_missing"),
        ({"repeated_image": None}, "repeatability", "repeat_render_missing"),
        ({"raster": None}, "raster_agreement", "independent_raster_evidence_missing"),
        ({"secondary_answer": None}, "reference_parity", "secondary_rule_evidence_missing"),
        ({"answerability": None}, "answerability", "answerability_evidence_missing"),
        (
            {"answerability": AnswerabilityEvidence(unique=True)},
            "answerability",
            "answer_margin_evidence_missing",
        ),
    ],
)
def test_missing_artifacts_and_checks_stay_pending(candidate, overrides, check, reason):
    report = validate_candidate(**(candidate | overrides))
    assert report.status == "pending"
    assert get_check(report, check).reason == reason


@pytest.mark.parametrize("path", ["../hidden.png", "images/../private.png", "C:/notes.png"])
def test_public_path_and_fields_are_strict(candidate, path):
    candidate["public"] |= {"image_path": path, "seed": 4}
    report = validate_candidate(**candidate)
    assert report.status == "rejected"
    assert get_check(report, "public_schema").reason == "invalid_public_task"


def test_public_and_private_records_need_matching_task_ids(candidate):
    candidate["private"]["task_id"] = "different-id"
    report = validate_candidate(**candidate)
    assert report.status == "rejected"
    assert get_check(report, "task_identity").reason == "public_private_task_ids_differ"


def test_response_schema_requires_reference_membership_and_local_resolution(candidate):
    schema = candidate["public"]["response_schema"]
    schema["properties"]["value"]["enum"] = ["STOPPED"]
    report = validate_candidate(**candidate)
    assert report.status == "rejected"
    assert get_check(report, "response_schema").reason == "reference_rejected_by_schema"

    candidate["public"]["response_schema"] = {"$ref": "https://example.invalid/private.json"}
    report = validate_candidate(**candidate)
    assert report.status == "rejected"
    assert get_check(report, "response_schema").reason == "invalid_or_unresolved_response_schema"


def test_image_hash_and_repeatability_fail_separately(candidate):
    candidate["private"]["image_sha256"] = "a" * 64
    candidate["repeated_image"] = png_bytes(width=95)
    report = validate_candidate(**candidate)
    assert report.status == "rejected"
    assert get_check(report, "image_hash").reason == "image_sha256_mismatch"
    assert get_check(report, "repeatability").reason == "repeat_render_sha256_mismatch"


def test_image_size_limit_applies_before_hashing(candidate, monkeypatch):
    monkeypatch.setattr(validation, "MAX_IMAGE_BYTES", len(candidate["image"]) - 1)
    report = validate_candidate(**candidate)
    assert report.status == "rejected"
    assert report.image_sha256 is None
    assert get_check(report, "png_container").reason == "image_byte_limit_exceeded"
    assert get_check(report, "repeatability").reason == "repeat_render_byte_limit_exceeded"


@pytest.mark.parametrize("corruption", ["truncate", "trailing", "checksum", "pixels"])
def test_invalid_png_container_or_raster_is_rejected(candidate, corruption):
    image = candidate["image"]
    if corruption == "truncate":
        image = image[:-1]
    elif corruption == "trailing":
        image += b"trailing data"
    else:
        image = bytearray(image)
        idat = image.index(b"IDAT")
        image[idat + 4] ^= 0xFF
        if corruption == "pixels":
            length = struct.unpack_from(">I", image, idat - 4)[0]
            end = idat + 4 + length
            struct.pack_into(">I", image, end, zlib.crc32(image[idat:end]))
        image = bytes(image)

    report = validate_candidate(**(candidate | {"image": image}))
    assert report.status == "rejected"
    assert get_check(report, "png_container").status == "fail"
    if corruption == "pixels":
        assert get_check(report, "png_container").reason == "png_decode_error"


def test_png_metadata_fails(candidate):
    metadata = PngInfo()
    metadata.add_text("comment", "fixture comment")
    report = validate_candidate(**(candidate | {"image": png_bytes(pnginfo=metadata)}))
    assert report.status == "rejected"
    assert get_check(report, "png_metadata").reason == "non_pixel_png_chunks"


@pytest.mark.parametrize(
    ("image", "reason"),
    [
        (png_bytes(width=91), "unexpected_image_dimensions"),
        (png_bytes(width=MAX_IMAGE_DIMENSION + 1, height=1), "image_dimensions_out_of_bounds"),
    ],
)
def test_png_dimension_limits(candidate, image, reason):
    report = validate_candidate(**(candidate | {"image": image}))
    assert report.status == "rejected"
    assert get_check(report, "image_dimensions").reason == reason


def test_evidence_bounds_verify_raster_and_private_regions(candidate):
    observed = EvidenceRegion(instrument_id="P1", x=95, y=25, width=3, height=8)
    raster = replace(candidate["raster"], observed_regions=(observed,))
    report = validate_candidate(**(candidate | {"raster": raster}))
    assert get_check(report, "evidence_bounds").reason == "evidence_region_out_of_bounds"

    candidate["private"]["evidence_regions"] = [observed.model_dump()]
    report = validate_candidate(**candidate)
    assert report.status == "rejected"
    assert get_check(report, "evidence_bounds").reason == "evidence_region_out_of_bounds"


@pytest.mark.parametrize(
    ("raster_changes", "reason"),
    [
        ({"image_sha256": "f" * 64}, "raster_trace_provenance_mismatch"),
        ({"task_id": "unrelated-task"}, "raster_trace_provenance_mismatch"),
        ({"outcome": "unreadable"}, "raster_evidence_unreadable_or_unsupported"),
        ({"recovered_answer": None}, "raster_trace_incomplete"),
        (
            {"recovered_answer": CategoryAnswer(kind="category", value="STOPPED")},
            "raster_answer_disagrees_with_reference",
        ),
    ],
)
def test_raster_evidence_must_belong_to_the_image_and_agree(candidate, raster_changes, reason):
    raster = replace(candidate["raster"], **raster_changes)
    report = validate_candidate(**(candidate | {"raster": raster}))
    assert report.status == "rejected"
    assert get_check(report, "raster_agreement").reason == reason


def test_ambiguous_and_insufficient_margin_candidates_fail(candidate):
    ambiguous = AnswerabilityEvidence(unique=False)
    report = validate_candidate(**(candidate | {"answerability": ambiguous}))
    assert report.status == "rejected"
    assert get_check(report, "answerability").reason == "answer_is_ambiguous"

    below_margin = replace(candidate["answerability"], observed_margin_milli_kpa=9_999)
    report = validate_candidate(**(candidate | {"answerability": below_margin}))
    assert report.status == "rejected"
    assert get_check(report, "answerability").reason == "insufficient_answer_margin"


def test_numeric_evidence_uses_reference_units_and_tolerance(candidate):
    reference = NumericAnswer(kind="numeric", unit="kPa", value_milli=100_000)
    observed = NumericAnswer(kind="numeric", unit="bar", value_milli=1_001)
    candidate["public"]["response_schema"] = {"type": "object"}
    candidate["private"] |= {"answer": reference.model_dump(), "tolerance_milli": 100}
    candidate["raster"] = replace(candidate["raster"], recovered_answer=observed)
    candidate["secondary_answer"] = reference
    candidate["answerability"] = AnswerabilityEvidence(unique=True, margin_required=False)

    assert validate_candidate(**candidate).status == "accepted"
    candidate["private"]["tolerance_milli"] = 99
    report = validate_candidate(**candidate)
    assert report.status == "rejected"
    assert get_check(report, "raster_agreement").reason == "raster_answer_disagrees_with_reference"


def test_report_summary_keeps_pending_and_rejected_counts(candidate):
    good = validate_candidate(**candidate)
    pending = validate_candidate(**(candidate | {"raster": None}))
    wrong = validate_candidate(
        **(candidate | {"secondary_answer": CategoryAnswer(kind="category", value="STOPPED")})
    )
    summary = summarize_reports([good, pending, wrong])
    assert summary["candidate_count"] == 3
    assert summary["status_counts"] == {"accepted": 1, "pending": 1, "rejected": 1}
    assert summary["skill_status_counts"]["operational_state"] == summary["status_counts"]
    assert summary["check_counts"]["raster_agreement"] == {
        "status_counts": {"pass": 2, "fail": 0, "pending": 1},
        "reason_counts": {
            "independent_raster_evidence_missing": 1,
            "raster_answer_matches_reference": 2,
        },
    }
