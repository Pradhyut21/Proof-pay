"""Run the independent Rust scene verifier using private JSONL records."""

import json
import os
import shutil
import subprocess
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


class RustVerificationError(RuntimeError):
    """The Rust verifier failed or returned malformed output."""


def verify_scenes(
    scenes: Iterable[Mapping[str, Any]],
    *,
    executable: str | os.PathLike[str] = "pp",
    required: bool = False,
    timeout_seconds: float = 30,
) -> list[dict[str, Any]] | None:
    """Return verified rows, or None if an optional Rust binary is absent."""
    binary = shutil.which(os.fspath(executable))
    if binary is None:
        if required:
            raise RustVerificationError(f"Rust verifier {os.fspath(executable)!r} was not found")
        return None

    records = list(scenes)
    if not records:
        return []
    payload = "".join(json.dumps(dict(scene), allow_nan=False) + "\n" for scene in records)
    try:
        process = subprocess.run(
            [os.fspath(Path(binary).resolve()), "verify", "--scenes", "-"],
            input=payload,
            capture_output=True,
            encoding="utf-8",
            check=True,
            timeout=timeout_seconds,
        )
    except subprocess.CalledProcessError as exc:
        raise RustVerificationError(f"Rust verifier failed: {exc.stderr.strip()}") from exc
    except (OSError, subprocess.TimeoutExpired, UnicodeDecodeError) as exc:
        raise RustVerificationError(f"Rust verifier could not run: {exc}") from exc
    try:
        verified = [json.loads(line) for line in process.stdout.splitlines() if line.strip()]
    except json.JSONDecodeError as exc:
        raise RustVerificationError("Rust verifier returned malformed JSONL") from exc
    if len(verified) != len(records) or any(
        not isinstance(result, dict) or result.get("base_scene_id") != scene.get("base_scene_id")
        for scene, result in zip(records, verified, strict=True)
    ):
        raise RustVerificationError("Rust verifier response does not match input scenes")
    return verified
