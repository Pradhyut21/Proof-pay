"""Build a local source release from an exact PanelProof Git commit."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from unicodedata import normalize

ROOT_FILES = {
    ".dockerignore",
    ".editorconfig",
    ".env.example",
    ".gitattributes",
    ".gitignore",
    ".pre-commit-config.yaml",
    "AGENTS.md",
    "Cargo.lock",
    "Cargo.toml",
    "CITATION.cff",
    "LICENSE",
    "LICENSE.md",
    "LICENSE.txt",
    "Makefile",
    "PRD.md",
    "README.md",
    "THIRD_PARTY_NOTICES.md",
    "compose.yaml",
    "run.ps1",
    "run.sh",
}
REQUIRED_NESTED_SOURCE = {
    "apps/web/.prettierignore",
    "apps/web/.prettierrc",
    "apps/web/lib/answers.ts",
    "infra/docker/api.Dockerfile",
    "infra/docker/web.Dockerfile",
}
SOURCE_DIRS = {
    ".github",
    "apps",
    "configs",
    "crates",
    "docs",
    "evals",
    "migrations",
    "python",
    "reference",
    "schemas",
    "scripts",
    "shared",
    "submission",
}
SOURCE_EXTENSIONS = {
    ".cjs",
    ".css",
    ".gitignore",
    ".html",
    ".js",
    ".json",
    ".jsonc",
    ".jsx",
    ".lock",
    ".md",
    ".mjs",
    ".ps1",
    ".py",
    ".rs",
    ".sh",
    ".sql",
    ".svg",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}
EXCLUDED_DIRECTORIES = {
    ".git",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "answer_keys",
    "build",
    "cache",
    "data",
    "datasets",
    "dist",
    "external",
    "frozen",
    "node_modules",
    "private",
    "results",
    "runs",
    "secrets",
    "target",
    "test_frozen",
    "venv",
}
EXCLUDED_STEMS = {
    "answer_key",
    "answers",
    "credentials",
    "hidden_records",
    "private_tasks",
    "secrets",
}
EMBEDDED_MANIFEST = "submission/manifest.json"
MAX_SOURCE_BYTES = 64 * 1024 * 1024
SECRET_SIGNATURE = re.compile(
    rb"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----|"
    rb"(?:sk-(?:ant-|proj-|svcacct-)?[A-Za-z0-9_-]{30,}|gh[pousr]_[A-Za-z0-9]{24,}|"
    rb"github_pat_[A-Za-z0-9_]{30,}|AKIA[A-Z0-9]{16})"
)
ENV_SECRET = re.compile(
    rb"^\s*(?:export\s+)?[A-Za-z0-9_]*(?:API_KEY|TOKEN|PASSWORD|SECRET)\s*=\s*([^\r\n]*)",
    re.MULTILINE,
)
WINDOWS_DEVICE = re.compile(
    r"(?:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|(?:COM|LPT)[1-9¹²³])", re.IGNORECASE
)


@dataclass(frozen=True)
class GitFile:
    path: str
    mode: int
    oid: str
    size: int


def _git(repo: Path, *args: str, input_bytes: bytes | None = None) -> bytes:
    try:
        result = subprocess.run(
            ["git", "--no-replace-objects", "-C", str(repo), *args],
            input=input_bytes,
            capture_output=True,
            check=True,
            timeout=45,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ValueError(
            f"Git {args[0]} failed. Check the repository and requested commit."
        ) from exc
    return result.stdout


def _source_path(path: str) -> bool:
    if path in REQUIRED_NESTED_SOURCE:
        return True
    entry = PurePosixPath(path)
    if len(entry.parts) == 1:
        return path in ROOT_FILES
    return (
        entry.parts[0] in SOURCE_DIRS
        and not EXCLUDED_DIRECTORIES.intersection(
            part.casefold() for part in entry.parts[:-1]
        )
        and not entry.name.casefold().startswith(".env")
        and entry.stem.casefold() not in EXCLUDED_STEMS
        and entry.suffix.casefold() in SOURCE_EXTENSIONS
        and path != EMBEDDED_MANIFEST
    )


def _tree_files(repo: Path, commit: str) -> list[GitFile]:
    names: set[str] = set()
    selected = []
    for row in _git(repo, "ls-tree", "-rlz", "--full-tree", commit).split(b"\0"):
        if not row:
            continue
        header, path_bytes = row.split(b"\t", maxsplit=1)
        path = path_bytes.decode("utf-8")
        if not _source_path(path):
            continue
        key = normalize("NFC", path).casefold()
        if key in names or any(
            part in {"", ".", ".."}
            or part.endswith((".", " "))
            or any(c in part for c in '\\:<>"|?*')
            or any(ord(c) < 32 for c in part)
            or WINDOWS_DEVICE.fullmatch(part.split(".", maxsplit=1)[0].rstrip(" "))
            is not None
            for part in path.split("/")
        ):
            raise ValueError("The tree contains a conflicting or unsafe source path.")
        names.add(key)
        mode, kind, oid, size = header.decode("ascii").split()
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise ValueError(f"Source path is not a regular Git file: {path}")
        selected.append(GitFile(path, int(mode, 8), oid, int(size)))
    if not selected:
        raise ValueError("The commit has no allowlisted source files.")
    if sum(file.size for file in selected) > MAX_SOURCE_BYTES:
        raise ValueError(
            "The selected source files exceed 64 MiB. Review the release tree."
        )
    return sorted(selected, key=lambda file: file.path)


def _check_contents(path: str, data: bytes) -> None:
    if SECRET_SIGNATURE.search(data):
        raise ValueError(
            f"Review possible credential material in committed source: {path}"
        )
    if path == ".env.example":
        for value in ENV_SECRET.findall(data):
            placeholder = value.strip().strip(b"\"'").lower()
            if placeholder and not placeholder.startswith(
                (b"replace_", b"your_", b"<")
            ):
                raise ValueError(
                    "Secret-valued entries in .env.example must use placeholders."
                )


def _add(
    archive: zipfile.ZipFile, path: str, data: bytes, mode: int = 0o100644
) -> None:
    member = zipfile.ZipInfo(f"panelproof/{path}", date_time=(1980, 1, 1, 0, 0, 0))
    member.create_system = 3
    member.external_attr = mode << 16
    archive.writestr(member, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def _json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode()


def _archive(repo: Path, commit: str) -> tuple[bytes, dict]:
    files = _tree_files(repo, commit)
    object_ids = "\n".join(file.oid for file in files) + "\n"
    source_blobs = io.BytesIO(
        _git(repo, "cat-file", "--batch", input_bytes=object_ids.encode())
    )
    target = io.BytesIO()
    manifest = {
        "artifact_kind": "source_only",
        "archive_root": "panelproof",
        "source_commit": commit,
        "files": [],
    }
    with zipfile.ZipFile(target, "w") as archive:
        for item in files:
            expected = f"{item.oid} blob {item.size}\n".encode()
            if source_blobs.readline() != expected:
                raise ValueError("Git returned an unexpected source object.")
            data = source_blobs.read(item.size)
            if len(data) != item.size or source_blobs.read(1) != b"\n":
                raise ValueError("Git returned an incomplete source object.")
            _check_contents(item.path, data)
            _add(archive, item.path, data, item.mode)
            manifest["files"].append(
                {
                    "path": item.path,
                    "bytes": item.size,
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
        _add(archive, EMBEDDED_MANIFEST, _json(manifest))
    return target.getvalue(), manifest


def release(repo: Path, rev: str, out_dir: Path) -> Path:
    """Write the source ZIP, content manifest and SHA-256 in a new output directory."""
    repo = repo.resolve(strict=True)
    if out_dir.is_symlink():
        raise ValueError("Choose an output path that is not a symbolic link.")
    out_dir = out_dir.resolve()
    commit = _git(
        repo, "rev-parse", "--verify", "--end-of-options", f"{rev}^{{commit}}"
    )
    commit = commit.decode("ascii").strip()
    git_dir = Path(
        _git(repo, "rev-parse", "--absolute-git-dir").decode().strip()
    ).resolve()
    if out_dir.is_relative_to(git_dir) or ".git" in (
        part.casefold() for part in out_dir.parts
    ):
        raise ValueError("Choose an output directory outside Git metadata.")
    if out_dir.exists():
        raise ValueError("Choose a new output directory. Existing paths are preserved.")

    contents, manifest = _archive(repo, commit)
    name = f"panelproof-source-{commit[:12]}.zip"
    checksum = hashlib.sha256(contents).hexdigest()
    sidecar = {**manifest, "archive": {"file": name, "sha256": checksum}}
    out_dir.mkdir()
    created: list[Path] = []
    try:
        for filename, data in (
            (name, contents),
            (f"{name}.sha256", f"{checksum}  {name}\n".encode()),
            ("manifest.json", _json(sidecar)),
        ):
            path = out_dir / filename
            with path.open("xb") as stream:
                created.append(path)
                stream.write(data)
    except OSError:
        for path in created:
            path.unlink(missing_ok=True)
        if not any(out_dir.iterdir()):
            out_dir.rmdir()
        raise
    return out_dir / name


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument(
        "--rev", default="HEAD", help="Commit, tag, or branch to resolve"
    )
    parser.add_argument(
        "--out-dir", type=Path, required=True, help="New directory for release files"
    )
    args = parser.parse_args()
    try:
        print(release(args.repo, args.rev, args.out_dir))
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Release failed: {exc}\n")


if __name__ == "__main__":
    main()
