import csv
import hashlib
import io
import json
import struct
import subprocess
import sys
import zipfile
import zlib
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "human_audit.py"


def invoke(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, args)], text=True, capture_output=True
    )


def chunk(name, data):
    return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data))


def png(*, with_metadata=False):
    header = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))
    metadata = chunk(b"tEXt", b"description\0excluded-reference") if with_metadata else b""
    pixels = chunk(b"IDAT", zlib.compress(b"\0\xff"))
    return b"\x89PNG\r\n\x1a\n" + header + metadata + pixels + chunk(b"IEND", b"")


def write_jsonl(path, records):
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")


@pytest.fixture
def bundle(tmp_path):
    root = tmp_path / "bundle"
    for folder in ("images", "public", "private"):
        (root / folder).mkdir(parents=True)
    cases = [
        ("first-opaque-id", "dev", "accepted", "operational_state"),
        ("second-opaque-id", "dev", "accepted", "reading"),
        ("held-out-opaque-id", "test_frozen", "accepted", "operational_state"),
        ("rejected-opaque-id", "dev", "rejected", "operational_state"),
        ("diagnostic-opaque-id", "diagnostic_abstain", "accepted", "operational_state"),
    ]
    public = []
    private = []
    for index, (task_id, split, state, skill) in enumerate(cases, 1):
        image = f"images/panel-{index}.png"
        (root / image).write_bytes(png())
        public.append(
            {
                "schema_version": "1.0.0",
                "task_id": task_id,
                "image_path": image,
                "question": (
                    "Visible question 2 & context. Return the value in thousandths of the displayed unit."
                    if skill == "reading" else f"Visible question {index} & context"
                ),
                "public_rules": "Use the panel.",
                "response_schema": {
                    "examples": ["excluded-schema-example"],
                    "properties": {
                        "kind": {"enum": ["numeric"]},
                        "unit": {"enum": ["bar"]},
                    } if skill == "reading" else {
                        "kind": {"enum": ["category"]},
                        "value": {
                            "enum": ["OPTION_A", "OPTION_B"],
                            "default": "excluded-schema-default",
                        },
                    },
                },
            }
        )
        private.append(
            {
                "task_id": task_id,
                "split": split,
                "validation_status": state,
                "skill": skill,
                "image_sha256": hashlib.sha256(png()).hexdigest(),
                "answer": "excluded-reference",
                "seed": "excluded-seed",
            }
        )
    write_jsonl(root / "public/tasks.jsonl", public)
    write_jsonl(root / "private/tasks.jsonl", private)
    return root, private


def test_pack_is_deterministic_and_pilot_order_is_preserved(bundle, tmp_path):
    dataset, _ = bundle
    selection = tmp_path / "selection.json"
    selection.write_text(
        json.dumps(
            {"task_ids": ["second-opaque-id", "first-opaque-id"], "seed": "excluded-pilot-seed"}
        ),
        encoding="utf-8",
    )
    archives = [tmp_path / "a.zip", tmp_path / "b.zip"]
    for archive in archives:
        result = invoke("prepare", "--dataset", dataset, "--out", archive, "--selection", selection)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["reviewed_tasks"] == 0
    assert archives[0].read_bytes() == archives[1].read_bytes()
    with zipfile.ZipFile(archives[0]) as packed:
        assert sorted(packed.namelist()) == [
            "INSTRUCTIONS.txt",
            "panels/R001.png",
            "panels/R002.png",
            "review.html",
            "reviewer_A.csv",
            "reviewer_B.csv",
        ]
        content = b"\n".join(packed.read(name) for name in packed.namelist())
        assert b"excluded-" not in content
        assert b"opaque-id" not in content
        page = packed.read("review.html").decode()
        assert page.index("Visible question 2") < page.index("Visible question 1")
        assert "Visible question 3" not in page
        assert "Visible question 4" not in page
        assert "Visible question 5" not in page
        assert "&amp; context" in page
        assert "Return the value in thousandths of the displayed unit" in page
        assert "A reading of 1.5 bar is entered as 1500 bar" in page
        assert "ordinary decimal" not in page
        assert '"1500 bar"' in packed.read("INSTRUCTIONS.txt").decode()
        for reviewer in "AB":
            form = list(
                csv.DictReader(io.StringIO(packed.read(f"reviewer_{reviewer}.csv").decode()))
            )
            assert [row["review_id"] for row in form] == ["R001", "R002"]
            assert all(
                row["reviewer"] == reviewer and not row["verdict"] and not row["answer"]
                for row in form
            )


def test_rejects_frozen_selection_and_metadata_and_preserves_existing_archive(bundle, tmp_path):
    dataset, private = bundle
    selection = tmp_path / "selection.json"
    output = tmp_path / "review.zip"
    selection.write_text('{"task_ids":["held-out-opaque-id"]}', encoding="utf-8")
    result = invoke("prepare", "--dataset", dataset, "--out", output, "--selection", selection)
    assert result.returncode == 2 and "accepted development tasks" in result.stderr
    assert not output.exists()
    selection.write_text('{"task_ids":["first-opaque-id"]}', encoding="utf-8")
    output.write_bytes(b"keep")
    result = invoke("prepare", "--dataset", dataset, "--out", output, "--selection", selection)
    assert result.returncode == 2 and output.read_bytes() == b"keep"
    poisoned = png(with_metadata=True)
    (dataset / "images/panel-1.png").write_bytes(poisoned)
    private[0]["image_sha256"] = hashlib.sha256(poisoned).hexdigest()
    write_jsonl(dataset / "private/tasks.jsonl", private)
    output = tmp_path / "unpublished.zip"
    result = invoke("prepare", "--dataset", dataset, "--out", output, "--selection", selection)
    assert result.returncode == 2 and "non-pixel metadata" in result.stderr
    assert "excluded-reference" not in result.stderr
    assert not output.exists()


def completed(path, reviewer, judgments):
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        csv_writer = csv.writer(output)
        csv_writer.writerow(["pack_id", "reviewer", "review_id", "verdict", "answer", "notes"])
        for index, (verdict, answer) in enumerate(judgments, 1):
            csv_writer.writerow(
                ["pack-" + "0" * 24, reviewer, f"R{index:03d}", verdict, answer, "private note"]
            )


def test_agreement_counts_valid_pairs_and_handles_empty_and_wrong_forms(tmp_path):
    first, second = tmp_path / "a.csv", tmp_path / "b.csv"
    completed(
        first,
        "A",
        [
            ("VALID", "12.5 kPa"),
            ("VALID", "LOW"),
            ("AMBIGUOUS", ""),
            ("INSUFFICIENT", ""),
            ("", ""),
        ],
    )
    completed(
        second,
        "B",
        [
            ("valid", " 12.5 kPa "),
            ("AMBIGUOUS", ""),
            ("AMBIGUOUS", ""),
            ("INSUFFICIENT", ""),
            ("VALID", "X"),
        ],
    )
    result = invoke("summarize", "--reviewer-a", first, "--reviewer-b", second)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["worksheet_tasks"] == 5
    primary = report["primary_verdict_agreement"]
    assert primary["n"] == 4 and primary["agreements"] == 3 and primary["rate"] == 0.75
    assert primary["cohen_kappa"] == pytest.approx(7 / 11)
    assert report["exact_answer_agreement"] == {
        "both_valid": 1,
        "n": 1,
        "agreements": 1,
        "rate": 1.0,
    }
    assert "private note" not in result.stdout and "12.5 kPa" not in result.stdout
    same = invoke("summarize", "--reviewer-a", first, "--reviewer-b", first)
    assert same.returncode == 2

    for reviewer, file in (("A", first), ("B", second)):
        completed(file, reviewer, [("", "")])
    empty = invoke("summarize", "--reviewer-a", first, "--reviewer-b", second)
    assert empty.returncode == 0, empty.stderr
    primary = json.loads(empty.stdout)["primary_verdict_agreement"]
    assert primary["n"] == 0 and primary["rate"] is None and primary["cohen_kappa"] is None
