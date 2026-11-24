"""Model transports with an explicit public-input boundary."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, TypedDict
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

PROMPT_VERSION = "panelproof-answer-v1"
ANTHROPIC_API_VERSION = "2026-10-21"
MAX_RESPONSE_BYTES = 1_048_576


class VisibleReading(TypedDict):
    value_milli: int
    unit: str


class VisiblePump(TypedDict):
    label: str
    gauges: dict[str, VisibleReading]
    lamps: dict[str, Literal["on", "off"]]


@dataclass(frozen=True)
class PublicInput:
    question: str
    public_rules: str
    response_schema: dict[str, Any]
    image_png: bytes | None = None
    visible_readings: tuple[VisiblePump, ...] | None = None

    def prompt(self) -> str:
        public_fields: dict[str, Any] = {
            "question": self.question,
            "public_rules": self.public_rules,
            "response_schema": self.response_schema,
        }
        note = ""
        if self.visible_readings is not None:
            public_fields["visible_readings"] = self.visible_readings
            note = " Each gauge value_milli is in thousandths of its displayed unit."
        body = json.dumps(
            public_fields,
            ensure_ascii=False,
            sort_keys=True,
        )
        return (
            f"Answer the task with a single JSON object matching its response_schema.{note}\n{body}"
        )


@dataclass(frozen=True)
class ModelReply:
    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    model_revision: str | None = None


class ProviderError(Exception):
    """Safe error code for a request with no usable provider response."""

    def __init__(self, code: str, *, retryable: bool = False):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class Adapter(Protocol):
    provider: str
    model_id: str
    revision: str | None

    def generate(self, payload: PublicInput, *, timeout: float, max_tokens: int) -> ModelReply: ...

    def redact(self, text: str) -> str: ...


@dataclass(frozen=True)
class DemoAdapter:
    """A fixed fixture response for exercising the pipeline."""

    answer: str = '{"kind":"category","value":"NORMAL"}'
    model_id: str = "panelproof-demo"
    revision: str = "1"
    provider: str = "demo"

    def generate(self, payload: PublicInput, *, timeout: float, max_tokens: int) -> ModelReply:
        return ModelReply(self.answer)

    def redact(self, text: str) -> str:
        return text


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _post_json(
    url: str, headers: dict[str, str], body: dict[str, Any], timeout: float
) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        status = exc.code
        exc.close()
        raise ProviderError(
            f"provider_http_{status}", retryable=status in {408, 429} or 500 <= status < 600
        ) from None
    except TimeoutError:
        raise ProviderError("provider_timeout", retryable=True) from None
    except URLError as exc:
        code = (
            "provider_timeout" if isinstance(exc.reason, TimeoutError) else "provider_unreachable"
        )
        raise ProviderError(code, retryable=True) from None
    except OSError:
        raise ProviderError("provider_connection_error", retryable=True) from None
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ProviderError("provider_response_too_large")
    try:
        data = json.loads(raw)
    except (ValueError, RecursionError):
        raise ProviderError("provider_invalid_envelope") from None
    if not isinstance(data, dict):
        raise ProviderError("provider_invalid_envelope")
    return data


def _usage_count(data: Any, key: str) -> int | None:
    count = data.get(key) if isinstance(data, dict) else None
    return count if type(count) is int and count >= 0 else None


def _model_reply(
    data: dict[str, Any], text: Any, input_key: str, output_key: str, model_id: str
) -> ModelReply:
    if not isinstance(text, str):
        raise ProviderError("provider_missing_text")
    usage = data.get("usage")
    reported = data.get("model")
    revision = reported if isinstance(reported, str) and reported != model_id else None
    return ModelReply(
        text, _usage_count(usage, input_key), _usage_count(usage, output_key), revision
    )


@dataclass(frozen=True)
class ApiAdapter:
    provider: str
    model_id: str
    revision: str | None
    endpoint: str
    api_key: str = field(repr=False)

    def __post_init__(self) -> None:
        url = urlsplit(self.endpoint)
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError("Model endpoint must use HTTPS without URL credentials.")
        if url.query or url.fragment:
            raise ValueError("Model endpoint must omit query parameters and fragments.")
        if not self.api_key:
            raise ValueError("Model API key is empty.")
        if self.provider not in {"openai_compatible", "anthropic"}:
            raise ValueError("Unsupported model provider.")

    def redact(self, text: str) -> str:
        return text.replace(self.api_key, "[REDACTED]")

    def generate(self, payload: PublicInput, *, timeout: float, max_tokens: int) -> ModelReply:
        content = [{"type": "text", "text": payload.prompt()}]
        image = base64.b64encode(payload.image_png).decode("ascii") if payload.image_png else None
        if self.provider == "anthropic":
            if image:
                content.append(
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/png", "data": image},
                    }
                )
            data = _post_json(
                self.endpoint,
                {"x-api-key": self.api_key, "anthropic-version": ANTHROPIC_API_VERSION},
                {
                    "model": self.model_id,
                    "max_tokens": max_tokens,
                    "messages": [{"role": "user", "content": content}],
                },
                timeout,
            )
            blocks = data.get("content")
            if not isinstance(blocks, list):
                raise ProviderError("provider_missing_text")
            texts = [block.get("text") for block in blocks if isinstance(block, dict)]
            answer = "".join(text for text in texts if isinstance(text, str))
            return _model_reply(data, answer, "input_tokens", "output_tokens", self.model_id)

        if image:
            content.append(
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image}"}}
            )
        data = _post_json(
            self.endpoint,
            {"Authorization": f"Bearer {self.api_key}"},
            {
                "model": self.model_id,
                "max_completion_tokens": max_tokens,
                "messages": [{"role": "user", "content": content}],
            },
            timeout,
        )
        try:
            answer = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ProviderError("provider_missing_text") from None
        return _model_reply(data, answer, "prompt_tokens", "completion_tokens", self.model_id)
