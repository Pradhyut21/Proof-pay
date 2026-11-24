import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "release.py"


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, check=True, text=True
    ).stdout.strip()


@pytest.fixture
def source(tmp_path):
    repo = tmp_path / "source"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "Release Fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "core.autocrlf", "false")
    tracked = {
        "README.md": "committed source\n",
        ".dockerignore": "data/build\n",
        "apps/web/.prettierrc": '{"semi": true}',
        "apps/web/.prettierignore": ".next\n",
        "apps/web/lib/answers.ts": "export const answerFormat = 'numeric';\n",
        "infra/docker/api.Dockerfile": "FROM debian:bookworm-slim\n",
        "infra/docker/web.Dockerfile": "FROM node:22-bookworm-slim\n",
        "docs/assets/evidence-inspector.png": "approved README image fixture\n",
        "docs/assets/unreviewed.png": "excluded general image fixture\n",
        "docs/results/integration_pilot.md": "# Approved aggregate pilot evidence\n",
        "docs/results/per_task.jsonl": '{"task_id":"private-fixture"}\n',
        "python/src/panelproof.py": "def status():\n    return 'ready'\n",
        ".env.example": "PANELPROOF_REVEAL_TOKEN=\n# Optional settings\nMODEL_API_KEY=REPLACE_WITH_KEY\n",
        ".env": "MODEL_API_KEY=fixture-redacted-secret\n",
        "datasets/external/gauge.json": '{"external":true}',
        "data/demo/private/keys.jsonl": '{"answer":true}',
        "python/private/answers.json": '{"answer":true}',
        "python/.venv/lib/ambient.py": "environment cache",
        "submission/manifest.json": "stale manifest",
    }
    for name, content in tracked.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode())
    git(repo, "add", "-f", ".")
    git(repo, "commit", "-m", "fixture")
    return repo


def invoke(repo, out, rev="HEAD"):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), "--rev", rev, "--out-dir", str(out)],
        capture_output=True,
        text=True,
    )


def test_release_pins_commit_and_excludes_working_tree_data(source, tmp_path):
    commit = git(source, "rev-parse", "HEAD")
    (source / "README.md").write_text("uncommitted source", encoding="utf-8")
    (source / "python" / "untracked.py").write_text("untracked source", encoding="utf-8")
    first, second = tmp_path / "first", tmp_path / "second"
    for target in (first, second):
        run = invoke(source, target, commit)
        assert run.returncode == 0, run.stderr
    name = f"panelproof-source-{commit[:12]}.zip"
    archive_path = first / name
    assert archive_path.read_bytes() == (second / name).read_bytes()
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    assert (first / f"{name}.sha256").read_text().strip() == f"{digest}  {name}"
    manifest = json.loads((first / "manifest.json").read_text())
    assert manifest["archive"] == {"file": name, "sha256": digest}
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.namelist() == [
            "panelproof/.dockerignore",
            "panelproof/.env.example",
            "panelproof/README.md",
            "panelproof/apps/web/.prettierignore",
            "panelproof/apps/web/.prettierrc",
            "panelproof/apps/web/lib/answers.ts",
            "panelproof/docs/assets/evidence-inspector.png",
            "panelproof/docs/results/integration_pilot.md",
            "panelproof/infra/docker/api.Dockerfile",
            "panelproof/infra/docker/web.Dockerfile",
            "panelproof/python/src/panelproof.py",
            "panelproof/submission/manifest.json",
        ]
        assert archive.read("panelproof/README.md") == b"committed source\n"
        embedded = json.loads(archive.read("panelproof/submission/manifest.json"))
        assert embedded["source_commit"] == commit
        for entry in embedded["files"]:
            data = archive.read(f"panelproof/{entry['path']}")
            assert entry["bytes"] == len(data)
            assert entry["sha256"] == hashlib.sha256(data).hexdigest()


def test_rejects_existing_output_and_git_metadata(source, tmp_path):
    target = tmp_path / "existing"
    target.mkdir()
    sibling = target / "keep.txt"
    sibling.write_text("keep", encoding="utf-8")
    exists = invoke(source, target)
    assert exists.returncode == 2 and sibling.read_text() == "keep"
    metadata = source / ".git" / "release-files"
    invalid = invoke(source, metadata)
    assert invalid.returncode == 2 and not metadata.exists()


def test_rejects_suspect_source_without_echoing_content(source, tmp_path):
    secret = "sk-" + "x" * 40
    (source / "README.md").write_text(secret, encoding="utf-8")
    git(source, "add", "README.md")
    git(source, "commit", "-m", "suspect fixture")
    out = tmp_path / "release"
    run = invoke(source, out)
    assert run.returncode == 2 and not out.exists()
    assert "possible credential material" in run.stderr and secret not in run.stderr


def test_rejects_nonplaceholder_env_values_after_blank_settings(source, tmp_path):
    secret = "staged-local-only-value"
    (source / ".env.example").write_text(
        f"PANELPROOF_REVEAL_TOKEN=\nMODEL_API_KEY={secret}\n", encoding="utf-8"
    )
    git(source, "add", ".env.example")
    git(source, "commit", "-m", "nonplaceholder fixture")
    out = tmp_path / "release"
    run = invoke(source, out)
    assert run.returncode == 2 and not out.exists()
    assert "must use placeholders" in run.stderr and secret not in run.stderr
