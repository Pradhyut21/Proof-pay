"""Run bounded model evaluations against public task records."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sqlite3
import struct
import sys
import tempfile
import time
import uuid
import zlib
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import TypeAdapter, ValidationError
from referencing import Registry
from referencing.exceptions import Unresolvable

from panelproof.adapters import (
    ANTHROPIC_API_VERSION,
    PROMPT_VERSION,
    Adapter,
    ApiAdapter,
    DemoAdapter,
    ProviderError,
    PublicInput,
    VisiblePump,
)
from panelproof.schemas import SCHEMA_VERSION, Answer, Attempt, PublicTask, Run

Condition = Literal["C0", "C1", "C3"]
CONDITIONS = ("C0", "C1", "C3")
_ANSWER = TypeAdapter(Answer)
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_IMAGE_CHUNKS = {b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS"}
_MICROS_PER_DOLLAR = 1_000_000
_MAX_MODEL_TEXT = 16_384


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def public_input_sha256(payload: PublicInput, image_sha256: str | None) -> str:
    """Commit to the exact prompt and, when sent, the PNG bytes."""
    return _digest(_canonical({"prompt": payload.prompt(), "image_sha256": image_sha256}))


def input_selection_sha256(inputs_by_task: dict[str, str]) -> str:
    return _digest(_canonical(inputs_by_task))


def _reject_constant(value: str) -> None:
    raise ValueError(f"unexpected JSON constant: {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj = dict(pairs)
    if len(obj) != len(pairs):
        raise ValueError("duplicate JSON field")
    return obj


def parse_answer(text: str, validator: Draft202012Validator) -> Answer:
    """Accept a single finite, duplicate-free JSON value matching both schemas."""
    if len(text) > _MAX_MODEL_TEXT:
        raise ValueError("model_answer_too_large")
    try:
        value = json.loads(text, parse_constant=_reject_constant, object_pairs_hook=_unique_object)
        answer = _ANSWER.validate_python(value, strict=True)
        conforms = validator.is_valid(value)
    except (ValueError, RecursionError) as exc:
        raise ValueError("invalid_answer_json") from exc
    except Unresolvable as exc:
        raise ValueError("unresolved_answer_schema_reference") from exc
    if not conforms:
        raise ValueError("answer_schema_mismatch")
    return answer


@dataclass(frozen=True)
class EvalLimits:
    max_calls: int = 25
    max_cost_micros: int = 0
    call_cost_ceiling_micros: int = 0
    max_tokens: int = 256
    max_retries: int = 1
    timeout_seconds: float = 20.0
    max_image_bytes: int = 4 * 1024 * 1024
    max_image_dimension: int = 2048

    def __post_init__(self) -> None:
        if min(self.max_calls, self.max_cost_micros, self.call_cost_ceiling_micros) < 0:
            raise ValueError("Call and cost limits must be nonnegative.")
        if self.max_tokens < 1 or not 0 <= self.max_retries <= 4:
            raise ValueError(
                "Token limit must be positive and retries must be between zero and four."
            )
        if not 0 < self.timeout_seconds <= 120:
            raise ValueError("Request timeout must be between zero and 120 seconds.")
        if min(self.max_image_bytes, self.max_image_dimension) < 1:
            raise ValueError("Image limits must be positive.")


@dataclass
class _Budget:
    limits: EvalLimits
    calls: int = 0

    def can_reserve(self) -> bool:
        next_calls = self.calls + 1
        return (
            next_calls <= self.limits.max_calls
            and next_calls * self.limits.call_cost_ceiling_micros <= self.limits.max_cost_micros
        )

    def reserve(self) -> bool:
        if not self.can_reserve():
            return False
        self.calls += 1
        return True


def _prepare_png(task: PublicTask, asset_root: Path, limits: EvalLimits) -> bytes:
    path = (asset_root / task.image_path).resolve()
    if not path.is_relative_to(asset_root.resolve()):
        raise ValueError("image_outside_asset_root")
    try:
        with path.open("rb") as stream:
            png = stream.read(limits.max_image_bytes + 1)
    except OSError:
        raise ValueError("image_unreadable") from None
    if len(png) > limits.max_image_bytes:
        raise ValueError("image_too_large")
    if len(png) < 33 or png[:8] != _PNG_MAGIC or png[8:16] != b"\0\0\0\rIHDR":
        raise ValueError("invalid_png")
    width, height = struct.unpack_from(">II", png, 16)
    if not 0 < min(width, height) <= max(width, height) <= limits.max_image_dimension:
        raise ValueError("image_dimensions_out_of_range")

    cursor = 8
    seen_data = False
    while cursor + 12 <= len(png):
        length, kind = struct.unpack_from(">I4s", png, cursor)
        chunk = cursor + 8 + length
        if chunk + 4 > len(png):
            break
        if kind not in _IMAGE_CHUNKS:
            raise ValueError("image_metadata_or_unsupported_chunk")
        expected_crc = struct.unpack_from(">I", png, chunk)[0]
        if zlib.crc32(memoryview(png)[cursor + 4 : chunk]) != expected_crc:
            break
        seen_data |= kind == b"IDAT"
        cursor = chunk + 4
        if kind == b"IEND":
            if length == 0 and cursor == len(png) and seen_data:
                return png
            break
    raise ValueError("invalid_png")


def _read_tasks(path: Path) -> list[PublicTask]:
    tasks: list[PublicTask] = []
    identifiers: set[str] = set()
    with path.open(encoding="utf-8") as stream:
        for index, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                task = PublicTask.model_validate_json(line)
            except ValidationError:
                raise ValueError(f"Invalid public task record on line {index}.") from None
            if task.task_id in identifiers:
                raise ValueError(f"Duplicate public task ID on line {index}.")
            identifiers.add(task.task_id)
            tasks.append(task)
    return tasks


@dataclass(frozen=True)
class C3Observations:
    readings_by_task: dict[str, tuple[VisiblePump, ...]]
    verified_images: int

    @property
    def digest(self) -> str:
        return _digest(_canonical(self.readings_by_task))


def _visible_readings(trace: dict[str, Any]) -> tuple[VisiblePump, ...]:
    if trace.get("status") != "verified" or not trace.get("pumps"):
        raise ValueError("panel readings are not verified")
    visible: list[VisiblePump] = []
    try:
        for pump in trace["pumps"]:
            label = pump["label"]
            if pump["verdict"] != "verified" or not isinstance(label, str) or not label.strip():
                raise ValueError("equipment label or readings are not verified")
            gauges = {}
            for role in ("INLET", "OUTLET"):
                unit = pump["gauges"][role]["unit"]
                value = pump["gauges"][role]["reading_milli"]
                if unit not in {"kPa", "bar", "psi"} or type(value) is not int:
                    raise ValueError("gauge reading or unit is not verified")
                gauges[role] = {"unit": unit, "value_milli": value}
            lamps = {role: pump["lamps"][role]["state"] for role in ("RUN", "ALARM")}
            if any(state not in {"on", "off"} for state in lamps.values()):
                raise ValueError("indicator state is not verified")
            visible.append({"label": label, "gauges": gauges, "lamps": lamps})
    except (KeyError, TypeError) as exc:
        raise ValueError("required visible observations are missing") from exc
    if len({pump["label"] for pump in visible}) != len(visible):
        raise ValueError("equipment labels are ambiguous")
    return tuple(sorted(visible, key=lambda pump: pump["label"]))


def prepare_c3_observations(
    tasks: list[PublicTask], asset_root: Path, limits: EvalLimits
) -> C3Observations:
    """Recover only visible readings from public PNGs, covering the entire cohort first."""
    from panelproof.verify import verify_png

    if not tasks or len({task.task_id for task in tasks}) != len(tasks):
        raise ValueError("C3 preflight requires a nonempty selection with unique task IDs.")
    readings_by_path: dict[str, tuple[VisiblePump, ...]] = {}
    readings_by_task = {}
    for task in tasks:
        try:
            if task.image_path not in readings_by_path:
                trace = verify_png(_prepare_png(task, asset_root, limits))
                readings_by_path[task.image_path] = _visible_readings(trace)
            readings_by_task[task.task_id] = readings_by_path[task.image_path]
        except ValueError as exc:
            raise ValueError(f"C3 preflight failed for task {task.task_id}: {exc}") from None
    return C3Observations(readings_by_task, len(readings_by_path))


def _selection(tasks: list[PublicTask], *, seed: int, limit: int) -> list[PublicTask]:
    return sorted(tasks, key=lambda task: _digest(_canonical([seed, task.task_id])))[:limit]


def _cache_key(
    adapter: Adapter, payload: PublicInput, condition: Condition, max_tokens: int
) -> str:
    model_config: str | dict[str, str] | None = None
    if isinstance(adapter, ApiAdapter):
        model_config = {
            "endpoint": adapter.endpoint,
            "api_version": ANTHROPIC_API_VERSION if adapter.provider == "anthropic" else "v1",
        }
    elif isinstance(adapter, DemoAdapter):
        model_config = adapter.answer
    return _digest(
        _canonical(
            {
                "provider": adapter.provider,
                "model": adapter.model_id,
                "revision": adapter.revision,
                "model_config": model_config,
                "condition": condition,
                "prompt_version": PROMPT_VERSION,
                "max_tokens": max_tokens,
                "prompt": payload.prompt(),
                "image_sha256": _digest(payload.image_png)
                if payload.image_png is not None
                else None,
            }
        )
    )


def _cached_answer(db: sqlite3.Connection, key: str) -> dict[str, Any] | None:
    found = db.execute("SELECT reply FROM cached_answer WHERE cache_key = ?", (key,)).fetchone()
    return json.loads(found[0]) if found else None


def _store_answer(db: sqlite3.Connection, key: str, attempt: Attempt) -> None:
    safe = attempt.model_dump(
        mode="json", include={"parsed_answer", "raw_output", "model_revision"}
    )
    with db:
        db.execute(
            "INSERT OR IGNORE INTO cached_answer (cache_key, reply) VALUES (?, ?)",
            (key, _canonical(safe)),
        )


def _has_sensitive_output(adapter: Adapter, answer: Answer) -> bool:
    if answer.kind == "category":
        return adapter.redact(answer.value) != answer.value
    if answer.kind == "set":
        return any(adapter.redact(item) != item for item in answer.values)
    return False


def _attempt(
    task: PublicTask,
    run: Run,
    adapter: Adapter,
    budget: _Budget,
    asset_root: Path,
    db: sqlite3.Connection,
    visible_readings: tuple[VisiblePump, ...] | None,
    inputs_by_task: dict[str, str],
) -> Attempt:
    start = time.monotonic()
    base = {
        "schema_version": SCHEMA_VERSION,
        "task_id": task.task_id,
        "run_id": run.run_id,
        "model_id": run.model_id,
        "provider": run.provider,
        "model_revision": run.model_revision,
        "condition": run.condition,
        "timestamp": datetime.now(UTC).isoformat(),
        "cached": False,
    }

    def record(status: str, **fields: Any) -> Attempt:
        return Attempt.model_validate(
            {
                **base,
                "status": status,
                "latency_ms": int(1000 * (time.monotonic() - start)),
                **fields,
            }
        )

    limits = budget.limits
    try:
        Draft202012Validator.check_schema(task.response_schema)
        validator = Draft202012Validator(task.response_schema, registry=Registry())
    except (SchemaError, RecursionError):
        return record("skipped", error="invalid_response_schema")
    try:
        image = _prepare_png(task, asset_root, limits) if run.condition == "C1" else None
    except ValueError as exc:
        return record("skipped", error=str(exc))
    payload = PublicInput(
        task.question, task.public_rules, task.response_schema, image, visible_readings
    )
    inputs_by_task[task.task_id] = public_input_sha256(
        payload, _digest(image) if image is not None else None
    )
    key = (
        _cache_key(adapter, payload, run.condition, limits.max_tokens) if adapter.revision else None
    )
    if key and (cached := _cached_answer(db, key)) is not None:
        return record("unscored", **cached, cached=True)

    for retry in range(limits.max_retries + 1):
        if not budget.reserve():
            return record("skipped", error="run_budget_exhausted")
        try:
            reply = adapter.generate(
                payload, timeout=limits.timeout_seconds, max_tokens=limits.max_tokens
            )
            break
        except ProviderError as exc:
            if not exc.retryable or retry == limits.max_retries or not budget.can_reserve():
                return record("provider_error", error=exc.code)
            time.sleep(0.25 * 2**retry)

    revision = adapter.redact(reply.model_revision) if reply.model_revision else run.model_revision
    usage = {"input_tokens": reply.input_tokens, "output_tokens": reply.output_tokens}
    try:
        if adapter.redact(reply.text) != reply.text:
            raise ValueError("sensitive_model_output")
        answer = parse_answer(reply.text, validator)
        if _has_sensitive_output(adapter, answer):
            raise ValueError("sensitive_model_output")
    except ValueError as exc:
        return record("invalid_response", error=str(exc), model_revision=revision, **usage)
    attempt = record(
        "unscored", parsed_answer=answer, raw_output=reply.text, model_revision=revision, **usage
    )
    if key and (reply.model_revision is None or reply.model_revision == adapter.revision):
        _store_answer(db, key, attempt)
    return attempt


def evaluate(
    tasks: list[PublicTask],
    *,
    asset_root: Path,
    adapter: Adapter,
    condition: Condition,
    seed: int,
    limits: EvalLimits,
    cache_path: Path,
) -> tuple[Run, list[Attempt], int]:
    """Return one run and one outcome per selected task, with actual invocation count."""
    if condition not in CONDITIONS:
        raise ValueError("Only C0, C1 and C3 are supported by this runner.")
    if len({task.task_id for task in tasks}) != len(tasks):
        raise ValueError("Each selected task ID must be unique within the run.")
    if (
        adapter.provider != "demo"
        and min(limits.max_cost_micros, limits.call_cost_ceiling_micros) <= 0
    ):
        raise ValueError(
            "Live evaluation requires a positive cost cap and per-request cost ceiling."
        )
    observations = prepare_c3_observations(tasks, asset_root, limits) if condition == "C3" else None
    sampling = {"max_tokens": limits.max_tokens, "max_retries": limits.max_retries}
    if observations is not None:
        sampling["c3_observations_sha256"] = observations.digest
    run = Run(
        schema_version=SCHEMA_VERSION,
        run_id=f"run-{uuid.uuid4().hex}",
        model_id=adapter.model_id,
        provider=adapter.provider,
        condition=condition,
        prompt_version=PROMPT_VERSION,
        seed=seed,
        max_calls=limits.max_calls,
        selected_task_ids_sha256=_digest(_canonical([task.task_id for task in tasks])),
        environment_fingerprint=f"{platform.system()}-{platform.machine()}-py{platform.python_version()}",
        demo_only=adapter.provider == "demo",
        model_revision=adapter.revision,
        sampling_parameters=sampling,
        max_cost_usd=limits.max_cost_micros / _MICROS_PER_DOLLAR,
    )
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    budget = _Budget(limits)
    inputs_by_task: dict[str, str] = {}
    with closing(sqlite3.connect(cache_path, timeout=30)) as db:
        with db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS cached_answer (cache_key TEXT PRIMARY KEY, reply BLOB NOT NULL)"
            )
        attempts = [
            _attempt(
                task,
                run,
                adapter,
                budget,
                asset_root,
                db,
                observations.readings_by_task[task.task_id] if observations is not None else None,
                inputs_by_task,
            )
            for task in tasks
        ]
    sampling["public_inputs_sha256"] = input_selection_sha256(inputs_by_task)
    run = run.model_copy(update={"sampling_parameters": sampling})
    return run, attempts, budget.calls


def _write_run(output_dir: Path, run: Run, attempts: list[Attempt]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    final = output_dir / run.run_id
    with tempfile.TemporaryDirectory(dir=output_dir, prefix=".panelproof-run-") as staging:
        stage = Path(staging)
        (stage / "run.json").write_text(run.model_dump_json(indent=2) + "\n", encoding="utf-8")
        (stage / "attempts.jsonl").write_text(
            "".join(attempt.model_dump_json() + "\n" for attempt in attempts), encoding="utf-8"
        )
        stage.rename(final)
    return final


def _money(value: str) -> int:
    try:
        decimal = Decimal(value) * _MICROS_PER_DOLLAR
        if not decimal.is_finite() or decimal < 0 or decimal != decimal.to_integral_value():
            raise InvalidOperation
        return int(decimal)
    except InvalidOperation:
        raise argparse.ArgumentTypeError(
            "expected a nonnegative USD amount with up to six decimals"
        ) from None


def _model_for(config: Path | None, model: str, *, dry_run: bool) -> Adapter:
    if model == "demo":
        return DemoAdapter()
    if config is None:
        raise ValueError("A registered live model requires --config.")
    try:
        registry = yaml.safe_load(config.read_text(encoding="utf-8"))["models"]
        item = registry[model]
        provider = item["provider"]
        model_id = item["model_id"]
        endpoint = item["endpoint"]
        env_name = item["api_key_env"]
        revision = item.get("revision")
    except (KeyError, TypeError, yaml.YAMLError):
        raise ValueError("Invalid model registry or unknown model name.") from None
    if not all(
        isinstance(value, str) and value for value in (provider, model_id, endpoint, env_name)
    ):
        raise ValueError(
            "Model registry entries require a provider, model ID, endpoint and key variable."
        )
    if revision is not None and (not isinstance(revision, str) or not revision):
        raise ValueError("Model revision must be a nonempty string.")
    key = "dry-run-placeholder" if dry_run else os.environ.get(env_name, "").strip()
    if not key:
        raise ValueError("Missing configured provider API key.")
    return ApiAdapter(provider, model_id, revision, endpoint, key)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path, required=True, help="public tasks.jsonl")
    parser.add_argument("--asset-root", type=Path, required=True, help="folder containing images/")
    parser.add_argument("--output-dir", type=Path, default=Path("results/runs"))
    parser.add_argument("--cache", type=Path, default=Path("results/runs/cache.sqlite3"))
    parser.add_argument("--config", type=Path, help="YAML model registry for live models")
    parser.add_argument("--model", default="demo", help="registered model name or demo")
    parser.add_argument("--condition", choices=CONDITIONS, default="C1")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--max-calls", type=int, default=25)
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--max-cost-usd", type=_money, default=0)
    parser.add_argument("--call-cost-ceiling-usd", type=_money, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-live", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.seed < 0 or args.limit < 1:
            raise ValueError("Seed must be nonnegative and limit must be positive.")
        if args.model != "demo" and not (args.allow_live or args.dry_run):
            raise ValueError("Live model runs require --allow-live.")
        limits = EvalLimits(
            max_calls=args.max_calls,
            max_cost_micros=args.max_cost_usd,
            call_cost_ceiling_micros=args.call_cost_ceiling_usd,
            max_tokens=args.max_tokens,
            max_retries=args.max_retries,
            timeout_seconds=args.timeout,
        )
        tasks = _selection(_read_tasks(args.tasks), seed=args.seed, limit=args.limit)
        adapter = _model_for(args.config, args.model, dry_run=args.dry_run)
        if not tasks:
            raise ValueError("No public tasks were selected.")
        if args.dry_run:
            c3 = (
                prepare_c3_observations(tasks, args.asset_root, limits)
                if args.condition == "C3"
                else None
            )
            ceiling = min(limits.max_calls, len(tasks) * (1 + limits.max_retries))
            if limits.call_cost_ceiling_micros:
                bounded = min(ceiling, limits.max_cost_micros // limits.call_cost_ceiling_micros)
            else:
                bounded = ceiling if args.model == "demo" else 0
            print(
                json.dumps(
                    {
                        "selected": len(tasks),
                        "selected_task_ids_sha256": _digest(
                            _canonical([task.task_id for task in tasks])
                        ),
                        "request_ceiling": ceiling,
                        "budgeted_request_ceiling": bounded,
                        "reserved_cost_ceiling_usd": (
                            bounded * limits.call_cost_ceiling_micros / _MICROS_PER_DOLLAR
                        ),
                        "model": args.model,
                        **(
                            {
                                "c3_observations_sha256": c3.digest,
                                "c3_verified_images": c3.verified_images,
                            }
                            if c3
                            else {}
                        ),
                    }
                )
            )
            return 0
        run, attempts, calls = evaluate(
            tasks,
            asset_root=args.asset_root,
            adapter=adapter,
            condition=args.condition,
            seed=args.seed,
            limits=limits,
            cache_path=args.cache,
        )
        destination = _write_run(args.output_dir, run, attempts)
        print(
            json.dumps(
                {
                    "run": str(destination),
                    "attempts": len(attempts),
                    "calls": calls,
                    "demo_only": run.demo_only,
                }
            )
        )
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(f"Evaluation failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
