import hashlib
import json
from pathlib import Path

import pytest

from panelproof import export

SEED = "0123456789abcdef" * 4
OTHER_SEED = "abcdef0123456789" * 4
TASK = {
    "schema_version": "1.0.0",
    "task_id": "t_fixture",
    "image_path": "images/fixture.png",
    "question": "What is the operating state?",
    "public_rules": "Read the panel to find its state.",
    "response_schema": {},
}


@pytest.fixture
def minimal_build(tmp_path, monkeypatch):
    cfg = tmp_path / "benchmark.yaml"
    cfg.write_text(
        'generator_config: configs/generator.yaml\ndataset_version: "0.1.0"\n'
        'repro_seed: "public-example"\nworkers: 1\n',
        encoding="utf-8",
    )

    def fixture_build(config, generator, out, workers, seed, metadata):
        image = out / TASK["image_path"]
        image.parent.mkdir()
        image.write_bytes(b"fixture image")
        export.jsonl(out / "public" / "frozen.jsonl", [TASK])
        export.jsonl(
            out / "private" / "answers.jsonl",
            [
                {
                    "task_id": TASK["task_id"],
                    "group_id": "group_fixture",
                    "split": "frozen_main",
                    "image": TASK["image_path"],
                    "seed": seed + ":00000",
                    "layout_family": "single",
                    "answer": {"kind": "category", "value": "NORMAL"},
                    "kind": "state",
                    "set": "main",
                    "alarm_on": False,
                }
            ],
        )
        return export._manifest(out, config, generator, metadata)

    monkeypatch.setattr(export, "_build_dataset", fixture_build)
    return cfg


def make_seed(path: Path, seed: str = SEED) -> Path:
    path.write_text(seed + "\n", encoding="ascii")
    return path


def test_public_repro_build_is_distinct_from_measured_holdout(minimal_build, tmp_path):
    repro = tmp_path / "repro"
    build = export.build_dataset(minimal_build, repro)
    assert build["dataset_purpose"] == "repro"
    assert "seed_commitment_sha256" not in build
    assert export.audit_dataset(repro, minimal_build)["rebuild_manifest_equal"]

    measured = tmp_path / "measured"
    seed = make_seed(tmp_path / "holdout-seed.txt")
    build = export.build_dataset(minimal_build, measured, holdout_seed_file=seed)
    assert build["dataset_purpose"] == "measured_holdout"
    assert build["seed_commitment_sha256"] == hashlib.sha256(SEED.encode("ascii")).hexdigest()
    assert SEED not in (measured / "manifest.json").read_text(encoding="utf-8")
    assert SEED not in (measured / "public/frozen.jsonl").read_text(encoding="utf-8")
    assert SEED in (measured / "private/answers.jsonl").read_text(encoding="utf-8")
    assert export.audit_dataset(measured)["pass"]
    assert export.audit_dataset(measured, minimal_build, holdout_seed_file=seed)["rebuild_manifest_equal"]

    with pytest.raises(ValueError, match="requires its local seed file"):
        export.audit_dataset(measured, minimal_build)
    with pytest.raises(ValueError, match="does not match"):
        export.audit_dataset(
            measured, minimal_build, holdout_seed_file=make_seed(tmp_path / "wrong-seed", OTHER_SEED)
        )


def test_measured_paths_cannot_live_in_git(minimal_build, tmp_path):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / ".git").mkdir()
    seed = make_seed(checkout / "seed.txt")
    with pytest.raises(ValueError, match="seed must be a regular file outside"):
        export.build_dataset(minimal_build, tmp_path / "measured", holdout_seed_file=seed)
    with pytest.raises(ValueError, match="output must be outside"):
        export.build_dataset(
            minimal_build, checkout / "measured", holdout_seed_file=make_seed(tmp_path / "outside")
        )


def test_invalid_seed_is_rejected_without_publishing(minimal_build, tmp_path):
    seed = make_seed(tmp_path / "seed.txt", "public-default")
    out = tmp_path / "measured"
    with pytest.raises(ValueError, match="64 random hexadecimal"):
        export.build_dataset(minimal_build, out, holdout_seed_file=seed)
    assert not out.exists()


def test_unowned_or_mixed_directories_survive_build(minimal_build, tmp_path):
    destination = tmp_path / "selected"
    destination.mkdir()
    notes = destination / "notes.txt"
    notes.write_text("irreplaceable", encoding="utf-8")
    with pytest.raises(ValueError, match="not empty or owned"):
        export.build_dataset(minimal_build, destination)
    assert notes.read_text(encoding="utf-8") == "irreplaceable"

    owned = tmp_path / "owned"
    export.build_dataset(minimal_build, owned)
    notes = owned / "added-later.txt"
    notes.write_text("keep this", encoding="utf-8")
    with pytest.raises(ValueError, match="unowned or missing"):
        export.build_dataset(minimal_build, owned)
    assert notes.read_text(encoding="utf-8") == "keep this"


def test_failed_build_does_not_remove_previous_dataset(minimal_build, tmp_path, monkeypatch):
    output = tmp_path / "previous"
    before = export.build_dataset(minimal_build, output)

    def fail_in_staging(_cfg, _gen, stage, _workers, _seed, _metadata):
        (stage / "partial.txt").write_text("staged", encoding="utf-8")
        raise RuntimeError("generation failed")

    monkeypatch.setattr(export, "_build_dataset", fail_in_staging)
    with pytest.raises(RuntimeError, match="generation failed"):
        export.build_dataset(minimal_build, output)

    assert json.loads((output / "manifest.json").read_text(encoding="utf-8")) == before
    assert not (output / "partial.txt").exists()
    assert not list(tmp_path.glob(".panelproof-stage-*"))


def test_staged_audit_rejects_invalid_manifest_before_publish(minimal_build, tmp_path, monkeypatch):
    before_build = export._build_dataset

    def record_drift(*args):
        result = before_build(*args)
        (args[2] / TASK["image_path"]).write_bytes(b"drift")
        return result

    monkeypatch.setattr(export, "_build_dataset", record_drift)
    output = tmp_path / "drift"
    with pytest.raises(ValueError, match="failed its artifact and split audit"):
        export.build_dataset(minimal_build, output)
    assert not output.exists()
    assert not list(tmp_path.glob(".panelproof-stage-*"))


def test_replacing_unchanged_owned_artifacts_is_safe(minimal_build, tmp_path):
    output = tmp_path / "same"
    assert export.build_dataset(minimal_build, output) == export.build_dataset(minimal_build, output)
    assert not list(tmp_path.glob(".panelproof-stage-*"))


def test_audit_refuses_bad_digest_and_outside_manifest_paths(minimal_build, tmp_path):
    output = tmp_path / "audit"
    export.build_dataset(minimal_build, output)
    path = output / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["public_files"]["../outside.txt"] = "0" * 64
    path.write_text(json.dumps(manifest), encoding="utf-8")
    result = export.audit_dataset(output)
    assert not result["pass"]
    assert not result["manifest_sha256_valid"]
    assert result["files_with_hash_drift"] == ["../outside.txt"]
