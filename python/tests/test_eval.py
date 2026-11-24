import json
import struct
import zlib

import pytest

from panelproof import adapters
from panelproof.adapters import ApiAdapter, ModelReply, ProviderError
from panelproof.evaluate import EvalLimits, evaluate, main
from panelproof.schemas import Attempt, PublicTask, Run

ANSWER = '{"kind":"category","value":"NORMAL"}'
SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"const": "category"},
        "value": {"enum": ["NORMAL", "LOW_PRESSURE", "STOPPED"]},
    },
    "required": ["kind", "value"],
    "additionalProperties": False,
}


def public_task(task_id, question="What classification applies?"):
    return PublicTask.model_validate(
        {
            "schema_version": "1.0.0",
            "task_id": task_id,
            "image_path": f"images/{task_id}.png",
            "question": question,
            "public_rules": "Compare the visible pressure readings.",
            "response_schema": SCHEMA,
        }
    )


def png(red=0, *, with_metadata=False):
    def chunk(kind, data):
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    metadata = chunk(b"tEXt", b"hidden\0private-value") if with_metadata else b""
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + metadata
        + chunk(b"IDAT", zlib.compress(bytes((0, red, 0, 0))))
        + chunk(b"IEND", b"")
    )


class StubAdapter:
    provider = "demo"
    model_id = "test-stub"
    revision = "fixed"

    def __init__(self, *replies):
        self.replies = iter(replies)
        self.payloads = []

    def generate(self, payload, *, timeout, max_tokens):
        self.payloads.append(payload)
        reply = next(self.replies)
        if isinstance(reply, ProviderError):
            raise reply
        return ModelReply(reply)

    def redact(self, text):
        return text


def run_eval(tmp_path, tasks, adapter, *, condition="C0", limits=None):
    return evaluate(
        tasks,
        asset_root=tmp_path,
        adapter=adapter,
        condition=condition,
        seed=0,
        limits=limits or EvalLimits(max_retries=0),
        cache_path=tmp_path / "cache.sqlite3",
    )


def test_payload_and_resume_cache_are_content_based(tmp_path):
    image_folder = tmp_path / "images"
    image_folder.mkdir()
    task = public_task("private-looking-id")
    image = tmp_path / task.image_path
    image.write_bytes(png())
    original = StubAdapter(ANSWER)
    run, attempts, calls = run_eval(tmp_path, [task], original, condition="C1")
    assert run.demo_only and calls == 1 and attempts[0].status == "unscored"
    payload = original.payloads[0]
    assert payload.image_png == png()
    assert payload.visible_readings is None
    assert set(json.loads(payload.prompt().split("\n", 1)[1])) == {
        "question",
        "public_rules",
        "response_schema",
    }
    assert task.task_id not in payload.prompt() and task.image_path not in payload.prompt()

    no_calls = StubAdapter()
    _, cached, calls = run_eval(tmp_path, [task], no_calls, condition="C1")
    assert calls == 0 and cached[0].cached
    assert cached[0].parsed_answer == attempts[0].parsed_answer

    image.write_bytes(png(red=12))
    _, changed, calls = run_eval(tmp_path, [task], StubAdapter(ANSWER), condition="C1")
    assert calls == 1 and not changed[0].cached


@pytest.mark.parametrize(
    "reply",
    [
        '```json\n{"kind":"category","value":"NORMAL"}\n```',
        '{"kind":"category","value":"NORMAL","value":"STOPPED"}',
        '{"kind":"category","value":"NOT_A_CATEGORY"}',
        '{"kind":"numeric","value_milli":5,"unit":"kPa"}',
        '{"kind":"numeric","value_milli":NaN,"unit":"kPa"}',
    ],
)
def test_invalid_answers_are_neither_scored_nor_retained(tmp_path, reply):
    _, attempts, calls = run_eval(tmp_path, [public_task("task1")], StubAdapter(reply))
    assert calls == 1 and attempts[0].status == "invalid_response"
    assert attempts[0].raw_output is None and attempts[0].parsed_answer is None


def test_timeout_retry_uses_the_call_budget(tmp_path):
    timeout = ProviderError("provider_timeout", retryable=True)
    adapter = StubAdapter(timeout, ANSWER)
    tasks = [public_task("task1"), public_task("task2", "A different question?")]
    _, attempts, calls = run_eval(
        tmp_path, tasks, adapter, limits=EvalLimits(max_calls=1, max_retries=3)
    )
    assert calls == 1
    assert [(item.status, item.error) for item in attempts] == [
        ("provider_error", "provider_timeout"),
        ("skipped", "run_budget_exhausted"),
    ]


def test_transient_failure_can_retry_within_budget(tmp_path, monkeypatch):
    backoffs = []
    monkeypatch.setattr("panelproof.evaluate.time.sleep", backoffs.append)
    adapter = StubAdapter(ProviderError("provider_http_429", retryable=True), ANSWER)
    _, attempts, calls = run_eval(
        tmp_path, [public_task("task1")], adapter, limits=EvalLimits(max_calls=2, max_retries=1)
    )
    assert calls == 2 and attempts[0].status == "unscored"
    assert backoffs == [0.25]


def test_schema_reference_does_not_fetch_external_resources(tmp_path):
    task = public_task("task1").model_copy(
        update={"response_schema": {"$ref": "https://example.invalid/schema"}}
    )
    _, attempts, calls = run_eval(tmp_path, [task], StubAdapter(ANSWER))
    assert calls == 1 and attempts[0].error == "unresolved_answer_schema_reference"


def test_oversized_and_metadata_bearing_images_skip_provider(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    task = public_task("task1")
    image = tmp_path / task.image_path
    image.write_bytes(png(with_metadata=True))
    adapter = StubAdapter()
    _, attempts, calls = run_eval(tmp_path, [task], adapter, condition="C1")
    assert calls == 0 and attempts[0].error == "image_metadata_or_unsupported_chunk"
    _, attempts, calls = run_eval(
        tmp_path, [task], adapter, condition="C1", limits=EvalLimits(max_image_bytes=40)
    )
    assert calls == 0 and attempts[0].error == "image_too_large"


def c3_trace(inlet=150_000):
    return {
        "status": "verified",
        "scene_id": "private-scene-id",
        "image_sha256": "private-image-hash",
        "pumps": [
            {
                "verdict": "verified",
                "label": "PUMP P-12",
                "pump_id": "private-pump-id",
                "gauges": {
                    "INLET": {
                        "unit": "kPa",
                        "reading_milli": inlet,
                        "private_hidden": "trace-marker",
                    },
                    "OUTLET": {"unit": "bar", "reading_milli": 5_500, "reading_mkpa": 550_000},
                },
                "lamps": {"RUN": {"state": "on"}, "ALARM": {"state": "off"}},
                "derived": {"state": "private-reference-answer", "expected_alarm": False},
            }
        ],
    }


def test_c3_provider_gets_visible_readings_only_and_cache_tracks_readings(tmp_path, monkeypatch):
    from panelproof import verify

    image_dir = tmp_path / "images"
    image_dir.mkdir()
    task = public_task("private-task-id")
    image_path = tmp_path / task.image_path
    image_path.write_bytes(png())
    monkeypatch.setattr(
        verify, "verify_png", lambda image: c3_trace(150_000 if image == png() else 160_000)
    )
    sent = []

    def transport(_url, _headers, body, _timeout):
        sent.append(body["messages"][0]["content"])
        return {"choices": [{"message": {"content": ANSWER}}]}

    monkeypatch.setattr(adapters, "_post_json", transport)
    adapter = ApiAdapter(
        "openai_compatible", "fixture-model", "v1", "https://provider.example/v1/test", "key"
    )
    limits = EvalLimits(max_cost_micros=20, call_cost_ceiling_micros=20)
    first, attempts, calls = run_eval(tmp_path, [task], adapter, condition="C3", limits=limits)
    assert calls == 1 and attempts[0].status == "unscored"
    assert len(sent[0]) == 1 and sent[0][0]["type"] == "text"
    text = sent[0][0]["text"]
    assert not any(
        term in text for term in ("private-", "trace-marker", "reading_mkpa", "expected_alarm")
    )
    assert json.loads(text.split("\n", 1)[1])["visible_readings"] == [
        {
            "label": "PUMP P-12",
            "gauges": {
                "INLET": {"unit": "kPa", "value_milli": 150_000},
                "OUTLET": {"unit": "bar", "value_milli": 5_500},
            },
            "lamps": {"RUN": "on", "ALARM": "off"},
        }
    ]
    _, cached, calls = run_eval(tmp_path, [task], adapter, condition="C3", limits=limits)
    assert not calls and cached[0].cached and len(sent) == 1
    image_path.write_bytes(png(red=12))
    changed, _, calls = run_eval(tmp_path, [task], adapter, condition="C3", limits=limits)
    assert calls == 1 and len(sent) == 2
    assert (
        first.sampling_parameters["c3_observations_sha256"]
        != changed.sampling_parameters["c3_observations_sha256"]
    )


def test_c3_unverified_task_blocks_entire_cohort_and_dry_run_uses_preflight(
    tmp_path, monkeypatch, capsys
):
    from panelproof import verify

    images = tmp_path / "images"
    images.mkdir()
    first, second = public_task("t1"), public_task("t2")
    (tmp_path / first.image_path).write_bytes(png())
    (tmp_path / second.image_path).write_bytes(png(red=1))
    monkeypatch.setattr(
        verify, "verify_png", lambda image: c3_trace() if image == png() else {"status": "rejected"}
    )
    stub = StubAdapter()
    with pytest.raises(ValueError, match="C3 preflight failed for task t2"):
        run_eval(tmp_path, [first, second], stub, condition="C3")
    assert stub.payloads == [] and not (tmp_path / "cache.sqlite3").exists()

    tasks = tmp_path / "tasks.jsonl"
    tasks.write_text(first.model_dump_json() + "\n", encoding="utf-8")
    args = ["--tasks", str(tasks), "--asset-root", str(tmp_path), "--condition", "C3", "--dry-run"]
    assert main(args) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["selected"] == plan["c3_verified_images"] == 1
    assert len(plan["c3_observations_sha256"]) == 64

    tasks.write_text(
        first.model_dump_json() + "\n" + second.model_dump_json() + "\n", encoding="utf-8"
    )
    assert main(args) == 2
    assert "C3 preflight failed for task t2" in capsys.readouterr().err


@pytest.mark.parametrize("provider", ["openai_compatible", "anthropic"])
def test_live_request_shapes_and_response_redaction(tmp_path, monkeypatch, provider):
    seen = []
    key = "secret-provider-key"

    def transport(url, headers, body, timeout):
        seen.append((url, headers, body, timeout))
        leaked_answer = json.dumps({"kind": "category", "value": key})
        return {
            "model": "model-resolved",
            "content": [{"type": "text", "text": leaked_answer}],
            "choices": [{"message": {"content": leaked_answer}}],
            "usage": {"prompt_tokens": 8, "input_tokens": 8},
        }

    monkeypatch.setattr(adapters, "_post_json", transport)
    task = public_task("private-id")
    image_folder = tmp_path / "images"
    image_folder.mkdir()
    (tmp_path / task.image_path).write_bytes(png())
    adapter = ApiAdapter(provider, "model", "pinned", "https://provider.example/v1/test", key)
    _, attempts, calls = run_eval(
        tmp_path,
        [task, public_task("task2")],
        adapter,
        condition="C1",
        limits=EvalLimits(max_cost_micros=20, call_cost_ceiling_micros=20),
    )
    assert calls == 1 and len(seen) == 1
    body = seen[0][2]
    assert task.task_id not in json.dumps(body) and key not in json.dumps(body)
    if provider == "anthropic":
        assert seen[0][1]["anthropic-version"] == adapters.ANTHROPIC_API_VERSION
    assert body["messages"][0]["content"][1]["type"] == (
        "image" if provider == "anthropic" else "image_url"
    )
    assert (
        attempts[0].status == "invalid_response" and attempts[0].error == "sensitive_model_output"
    )
    assert attempts[0].input_tokens == 8 and key not in attempts[0].model_dump_json()


def test_redacts_escaped_provider_key_after_parsing(tmp_path, monkeypatch):
    key = "secret-provider-key"
    reply = '{"kind":"category","value":"\\u0073ecret-provider-key"}'
    assert key not in reply
    monkeypatch.setattr(
        adapters,
        "_post_json",
        lambda *args: {"choices": [{"message": {"content": reply}}]},
    )
    base = public_task("task1")
    schema = {
        **base.response_schema,
        "properties": {"kind": {"const": "category"}, "value": {"type": "string"}},
    }
    task = base.model_copy(update={"response_schema": schema})
    adapter = ApiAdapter(
        "openai_compatible", "model", "pinned", "https://provider.example/v1/test", key
    )
    _, attempts, _ = run_eval(
        tmp_path,
        [task],
        adapter,
        limits=EvalLimits(max_cost_micros=20, call_cost_ceiling_micros=20),
    )
    assert attempts[0].error == "sensitive_model_output"
    assert key not in attempts[0].model_dump_json()


def test_unpinned_or_differently_reported_live_revisions_are_not_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(
        adapters,
        "_post_json",
        lambda *args: {"model": "reported-v2", "choices": [{"message": {"content": ANSWER}}]},
    )
    task = public_task("task1")
    limits = EvalLimits(max_cost_micros=20, call_cost_ceiling_micros=20)
    for revision in (None, "expected-v1"):
        adapter = ApiAdapter(
            "openai_compatible", "model", revision, "https://provider.example/v1/test", "key-value"
        )
        for _ in range(2):
            _, attempts, calls = run_eval(tmp_path, [task], adapter, limits=limits)
            assert calls == 1 and attempts[0].model_revision == "reported-v2"
            assert not attempts[0].cached


def test_spend_ceiling_prevents_extra_live_calls(tmp_path, monkeypatch):
    count = 0

    def transport(url, headers, body, timeout):
        nonlocal count
        count += 1
        return {"choices": [{"message": {"content": ANSWER}}]}

    monkeypatch.setattr(adapters, "_post_json", transport)
    adapter = ApiAdapter(
        "openai_compatible", "model", "pinned", "https://provider.example/v1/test", "key-value"
    )
    tasks = [public_task("task1", "Question 1?"), public_task("task2", "Question 2?")]
    _, attempts, calls = run_eval(
        tmp_path, tasks, adapter, limits=EvalLimits(max_cost_micros=25, call_cost_ceiling_micros=15)
    )
    assert count == calls == 1
    assert [attempt.status for attempt in attempts] == ["unscored", "skipped"]


def test_cli_dry_run_then_real_offline_artifact(tmp_path, capsys):
    tasks = tmp_path / "tasks.jsonl"
    tasks.write_text(public_task("task1").model_dump_json() + "\n", encoding="utf-8")
    output = tmp_path / "output"
    args = [
        "--tasks",
        str(tasks),
        "--asset-root",
        str(tmp_path),
        "--condition",
        "C0",
        "--output-dir",
        str(output),
        "--cache",
        str(tmp_path / "cache.sqlite3"),
    ]
    assert main([*args, "--dry-run"]) == 0 and not output.exists()
    plan = json.loads(capsys.readouterr().out)
    assert plan["selected"] == 1
    assert main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["demo_only"] and result["calls"] == 1
    run_folder = next(output.iterdir())
    run = Run.model_validate_json((run_folder / "run.json").read_text(encoding="utf-8"))
    attempts = [
        Attempt.model_validate_json(row)
        for row in (run_folder / "attempts.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert attempts[0].run_id == run.run_id and attempts[0].status == "unscored"
