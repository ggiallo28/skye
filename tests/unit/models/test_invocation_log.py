"""One structured log event per phase of a model invocation (Requirement 18.3)."""

from __future__ import annotations

import email.message
import io
import json
import logging
import urllib.error
from typing import Any
from unittest.mock import patch

import pytest

import skye
from skye.base.exceptions import ServerError
from skye.models.plugins.openai.provider import OpenAIProvider
from skye.models.utilities.rest import wrap

SECRET = "mario.rossi@example.com wants the quarterly report"


class _Body(io.BytesIO):
    status = 200

    def __enter__(self) -> _Body:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


REPLY = {
    "id": "c1",
    "object": "chat.completion",
    "created": 1700000000,
    "model": "gpt-4",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "done"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500},
}


def _client(**config: Any) -> OpenAIProvider:
    return OpenAIProvider(api_key="k", retry_sleep=lambda seconds: None, **config)


async def _agen(items: Any) -> Any:
    """The events as an async generator: what a provider's async stream transport returns."""
    for item in items:
        yield item


def _events(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if getattr(r, "skye_phase", None)]


def _delta(text: str | None, finish: str | None = None) -> Any:
    delta = {} if text is None else {"content": text}
    return wrap({"id": "s", "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]})


def test_a_call_logs_a_start_and_an_end_with_one_correlation_id(caplog: pytest.LogCaptureFixture) -> None:
    client = _client()
    with caplog.at_level(logging.DEBUG, logger="skye.models"):
        with patch("urllib.request.urlopen", lambda req, timeout=0: _Body(json.dumps(REPLY).encode())):
            client.complete(SECRET, model="gpt-4")
    start, end = _events(caplog)
    assert (start.skye_phase, start.levelno) == ("start", logging.DEBUG)
    assert (end.skye_phase, end.levelno) == ("end", logging.INFO)
    assert start.skye_correlation_id == end.skye_correlation_id
    assert start.skye_provider == "openai" and start.skye_model == "gpt-4"
    assert start.skye_request["messages"] == 1 and start.skye_request["stream"] is False
    response = end.skye_response
    assert (response["prompt_tokens"], response["completion_tokens"], response["finish_reason"]) == (1000, 500, "stop")
    assert response["cost"]["total"] == pytest.approx(0.06) and response["latency_ms"] >= 0


def test_no_message_content_reaches_the_log(caplog: pytest.LogCaptureFixture) -> None:
    client = _client()
    with caplog.at_level(logging.DEBUG, logger="skye.models"):
        with patch("urllib.request.urlopen", lambda req, timeout=0: _Body(json.dumps(REPLY).encode())):
            client.complete(SECRET, model="gpt-4")
    assert "mario.rossi" not in "".join(f"{r.getMessage()} {r.__dict__}" for r in _events(caplog))


def test_a_failed_call_logs_one_error_after_the_retries(caplog: pytest.LogCaptureFixture) -> None:
    client = _client()
    error = urllib.error.HTTPError("https://x", 503, "down", email.message.Message(), io.BytesIO(b"{}"))
    attempts: list[Any] = []

    def failing(req: Any, timeout: float = 0) -> Any:
        attempts.append(req)
        raise error

    with caplog.at_level(logging.DEBUG, logger="skye.models"):
        with patch("urllib.request.urlopen", failing), pytest.raises(ServerError):
            client.complete("hi", model="gpt-4")
    assert len(attempts) == 4  # 1 + 3 retries
    start, failed = _events(caplog)
    assert (failed.skye_phase, failed.levelno) == ("error", logging.WARNING)
    assert failed.skye_correlation_id == start.skye_correlation_id
    assert failed.skye_error.startswith("ServerError")


def test_a_stream_logs_its_end_with_the_last_running_count(caplog: pytest.LogCaptureFixture) -> None:
    usage_chunk = wrap({"id": "s", "choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}})
    client = _client()
    client._acall_provider_stream = lambda request: _agen(  # type: ignore[method-assign]
        [_delta("Hello"), _delta(None, "stop"), usage_chunk]
    )
    with caplog.at_level(logging.DEBUG, logger="skye.models"):
        list(client.stream("hi", model="gpt-4"))
    start, end = _events(caplog)
    assert start.skye_request["stream"] is True and start.skye_correlation_id == end.skye_correlation_id
    response = end.skye_response
    assert response["finish_reason"] == "stop"
    assert (response["prompt_tokens"], response["completion_tokens"], response["total_tokens"]) == (7, 3, 10)
    assert response["cost"]["exact"] is True


def test_a_stream_the_caller_abandons_is_still_logged(caplog: pytest.LogCaptureFixture) -> None:
    client = _client()
    client._acall_provider_stream = lambda request: _agen([_delta("one"), _delta("two"), _delta("three")])  # type: ignore[method-assign]
    with caplog.at_level(logging.DEBUG, logger="skye.models"):
        chunks = client.stream("hi", model="gpt-4")
        next(chunks)
        chunks.close()
    _, end = _events(caplog)
    assert end.skye_phase == "end" and end.skye_response["finish_reason"] == "interrupted"
    assert end.skye_response["completion_tokens"] >= 1


def test_a_stream_that_fails_logs_an_error(caplog: pytest.LogCaptureFixture) -> None:
    async def broken(request: Any) -> Any:
        yield _delta("partial")
        raise ServerError("dropped", provider="openai", status_code=503)

    client = _client()
    client._acall_provider_stream = broken  # type: ignore[method-assign]
    with caplog.at_level(logging.DEBUG, logger="skye.models"):
        with pytest.raises(ServerError):
            list(client.stream("hi", model="gpt-4"))
    phases = [r.skye_phase for r in _events(caplog)]
    assert phases == ["start", "error"]


def test_a_logging_failure_never_breaks_the_call(caplog: pytest.LogCaptureFixture) -> None:
    def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("cannot build")

    client = _client()
    with patch("skye.models.base.model_invocation_end", boom), caplog.at_level(logging.DEBUG, logger="skye.models"):
        with patch("urllib.request.urlopen", lambda req, timeout=0: _Body(json.dumps(REPLY).encode())):
            response = client.complete("hi", model="gpt-4")
    assert response.content == "done"
    assert [r.skye_phase for r in _events(caplog)] == ["start"]


def test_the_provider_name_comes_from_the_class_when_it_has_none() -> None:
    assert skye.provider("openai", api_key="k")._log_provider() == "openai"
    bedrock = skye.provider("bedrock", region_name="us-east-1", aws_access_key_id="a", aws_secret_access_key="b")
    assert bedrock._log_provider() == "bedrock"
    google = skye.provider("google", project_id="p", location="us-central1", credentials="token")
    assert google._log_provider() == "google"
