"""Regressions for the code issues the documentation review found in ``models`` (2026-11-11).

Findings 9 to 18. Each test failed on the code before the fix: retries (D104), Google location,
structured output with tools, a non-blocking ``astream``, the Bedrock region, standard key
variables (D18), Cohere through ``provider``, Azure Entra ID, a registry as ``capabilities``, and
the check of an ``OutputSchema`` reply against the whole schema.
"""

from __future__ import annotations

import asyncio
import email.message
import io
import json
import threading
import time
import urllib.error
from collections.abc import Iterator
from typing import Any
from unittest.mock import patch

import pytest

import skye
from skye.base.completion import CompleteRequest, StreamChunk
from skye.base.exceptions import (
    AuthenticationError,
    BadRequestError,
    ConfigurationError,
    ContentPolicyError,
    ProviderError,
    ProviderTimeoutError,
    RateLimitError,
    ServerError,
    ValidationError,
)
from skye.base.interfaces.capability import CapabilitySchema
from skye.base.messages import UserMessage
from skye.base.prompt_parts import OutputSchema
from skye.models.plugins.anthropic.provider import AnthropicProvider
from skye.models.plugins.azure.provider import AzureOpenAIProvider
from skye.models.plugins.bedrock.provider import BedrockProvider
from skye.models.plugins.openai.provider import OpenAIProvider
from skye.models.utilities.error_mapping import ErrorHandler
from skye.models.utilities.structured import parse_structured

CHAT_OK = {
    "id": "c1",
    "object": "chat.completion",
    "created": 1700000000,
    "model": "gpt-4",
    "choices": [
        {"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}
    ],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
}


class _Body(io.BytesIO):
    status = 200

    def __enter__(self) -> _Body:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _http_error(
    status: int, body: str = "{}", retry_after: str | None = None
) -> urllib.error.HTTPError:
    headers = email.message.Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError("https://x", status, "error", headers, io.BytesIO(body.encode()))


class _Script:
    """A fake ``urlopen`` that plays a list of outcomes (an exception, or a JSON or bytes body)."""

    def __init__(self, *outcomes: Any) -> None:
        self.outcomes = list(outcomes)
        self.requests: list[Any] = []

    def __call__(self, req: Any, timeout: float = 0) -> _Body:
        self.requests.append(req)
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, BaseException):
            raise outcome
        if isinstance(outcome, bytes):
            return _Body(outcome)
        return _Body(json.dumps(outcome).encode())


def _client(**config: Any) -> OpenAIProvider:
    waits: list[float] = []
    client = OpenAIProvider(api_key="k", retry_sleep=waits.append, **config)
    client.waits = waits  # type: ignore[attr-defined]
    return client


# --- D104 / finding 10: who retries, and what -----------------------------------------------------


@pytest.mark.parametrize(
    ("outcome", "error"),
    [
        (_http_error(429), RateLimitError),
        (_http_error(503), ServerError),
        (urllib.error.URLError(TimeoutError("timed out")), ProviderTimeoutError),
    ],
)
def test_transient_errors_are_retried(outcome: Any, error: type[ProviderError]) -> None:
    client = _client()
    script = _Script(outcome, CHAT_OK)
    with patch("urllib.request.urlopen", script):
        response = client.complete("hi", model="gpt-4")
    assert response.content == "hi"
    assert len(script.requests) == 2 and len(client.waits) == 1  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (401, "{}", AuthenticationError),
        (403, "{}", AuthenticationError),
        (400, "{}", BadRequestError),
        (400, '{"error": {"code": "content_filter"}}', ContentPolicyError),
        (404, "{}", BadRequestError),
    ],
)
def test_client_errors_are_raised_at_once_with_their_class(
    status: int, body: str, error: type[ProviderError]
) -> None:
    client = _client()
    script = _Script(_http_error(status, body))
    with patch("urllib.request.urlopen", script), pytest.raises(error) as caught:
        client.complete("hi", model="gpt-4")
    assert len(script.requests) == 1 and client.waits == []  # type: ignore[attr-defined]
    assert caught.value.status_code == status and caught.value.provider == "openai"


def test_retry_after_is_honoured_and_backoff_grows() -> None:
    client = _client(max_retries=3)
    script = _Script(_http_error(429, retry_after="7"), _http_error(500), _http_error(500), CHAT_OK)
    with patch("urllib.request.urlopen", script):
        client.complete("hi", model="gpt-4")
    waits = client.waits  # type: ignore[attr-defined]
    assert waits[0] == 7.0
    assert waits[1] < waits[2]


def test_retries_stop_after_max_retries_and_raise_the_last_error() -> None:
    client = _client(max_retries=2)
    script = _Script(_http_error(503))
    with patch("urllib.request.urlopen", script), pytest.raises(ServerError):
        client.complete("hi", model="gpt-4")
    assert len(script.requests) == 3


def test_max_retries_zero_turns_retries_off() -> None:
    client = _client(max_retries=0)
    assert client.max_retries == 0
    script = _Script(_http_error(429))
    with patch("urllib.request.urlopen", script), pytest.raises(RateLimitError):
        client.complete("hi", model="gpt-4")
    assert len(script.requests) == 1
    client.max_retries = 1
    script = _Script(_http_error(429), CHAT_OK)
    with patch("urllib.request.urlopen", script):
        client.complete("hi", model="gpt-4")
    assert len(script.requests) == 2


def test_provider_passes_max_retries_through() -> None:
    client = skye.provider("openai", api_key="k", max_retries=0)
    assert client.max_retries == 0


def _sse(*events: dict[str, Any]) -> bytes:
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events).encode() + b"data: [DONE]\n\n"


STREAM_OK = _sse(
    {"id": "s", "choices": [{"index": 0, "delta": {"content": "a"}, "finish_reason": None}]},
    {"id": "s", "choices": [{"index": 0, "delta": {"content": "b"}, "finish_reason": "stop"}]},
)


def test_streaming_retries_before_the_first_chunk() -> None:
    client = _client()
    script = _Script(_http_error(503), STREAM_OK)
    with patch("urllib.request.urlopen", script):
        text = "".join(chunk.delta for chunk in client.stream("hi", model="gpt-4"))
    assert text == "ab" and len(script.requests) == 2


def test_streaming_does_not_retry_after_the_first_chunk() -> None:
    client = _client()

    class Broken(_Body):
        def __iter__(self) -> Iterator[bytes]:
            yield b'data: {"id": "s", "choices": [{"index": 0, "delta": {"content": "a"}}]}\n'
            yield b"\n"
            raise ConnectionResetError("dropped")

    calls: list[Any] = []

    def urlopen(req: Any, timeout: float = 0) -> _Body:
        calls.append(req)
        return Broken(b"")

    received: list[str] = []
    with patch("urllib.request.urlopen", urlopen), pytest.raises(ProviderTimeoutError):
        for chunk in client.stream("hi", model="gpt-4"):
            received.append(chunk.delta)
    assert received == ["a"] and len(calls) == 1


def test_error_mapping_builds_the_subclasses() -> None:
    class RateLimitedError(Exception):
        status_code = 429

    class DownError(Exception):
        status_code = 503

    class UnauthorizedError(Exception):
        status_code = 401

    limited = ErrorHandler.handle_openai_error(RateLimitedError("slow down"))
    assert isinstance(limited, RateLimitError)
    assert isinstance(ErrorHandler.handle_anthropic_error(DownError("x")), ServerError)
    assert isinstance(ErrorHandler.handle_azure_error(UnauthorizedError("x")), AuthenticationError)
    assert isinstance(
        ErrorHandler.handle_openai_error(TimeoutError("timeout")), ProviderTimeoutError
    )
    throttled = Exception("throttled")
    throttled.response = {"Error": {"Code": "ThrottlingException"}}  # type: ignore[attr-defined]
    assert isinstance(ErrorHandler.handle_bedrock_error(throttled), RateLimitError)
    assert isinstance(
        ErrorHandler.wrap_provider_error(TimeoutError("t"), "other"), ProviderTimeoutError
    )


# --- finding 9: Google keeps its location ---------------------------------------------------------


def test_google_keeps_location() -> None:
    client = skye.provider("google", project_id="p", location="europe-west4", credentials="token")
    assert client.location == "europe-west4"
    client = skye.provider("google", project_id="p", region="europe-west1", credentials="token")
    assert client.location == "europe-west1"


@pytest.mark.parametrize("name", ["google", "google-multimodal"])
def test_google_embeddings_through_provider(name: str) -> None:
    embedder = skye.provider(
        name,
        project_id="p",
        location="europe-west4",
        model="text-embedding-005",
        provider_type="embedding",
    )
    assert embedder.location == "europe-west4"


def test_bedrock_still_takes_region() -> None:
    client = skye.provider("bedrock", region="eu-west-1")
    assert client.region_name == "eu-west-1"


# --- finding 11: output schema with tools on Anthropic and Bedrock --------------------------------


class _Capability:
    def get_schema(self) -> CapabilitySchema:
        return CapabilitySchema(
            name="lookup",
            description="Look up a word",
            parameters={"type": "object", "properties": {"q": {"type": "string"}}},
        )


ANSWER = OutputSchema(
    "answer", {"type": "object", "properties": {"word": {"type": "string"}}, "required": ["word"]}
)


def test_anthropic_sends_the_schema_with_tools() -> None:
    client = AnthropicProvider(api_key="k")
    body = client._transform_request(
        CompleteRequest(
            messages=[UserMessage(content="x")],
            model="m",
            capabilities=[_Capability()],
            response_schema=ANSWER,
        )
    )
    assert [tool["name"] for tool in body["tools"]] == ["lookup"]
    fmt = body["output_config"]["format"]
    assert fmt["type"] == "json_schema" and fmt["schema"]["properties"]["word"] == {
        "type": "string"
    }
    assert fmt["schema"]["additionalProperties"] is False


def test_bedrock_sends_the_schema_with_tools_as_text() -> None:
    client = BedrockProvider(region_name="us-west-2")
    body = client._transform_request(
        CompleteRequest(
            messages=[UserMessage(content="x")],
            model="m",
            capabilities=[_Capability()],
            response_schema=ANSWER,
        )
    )
    assert [tool["toolSpec"]["name"] for tool in body["toolConfig"]["tools"]] == ["lookup"]
    assert any('"word"' in block["text"] for block in body["system"])


# --- finding 12: astream does not block the event loop --------------------------------------------


def test_astream_does_not_block_the_event_loop() -> None:
    client = _client()

    def slow_stream(*args: Any, **kwargs: Any) -> Iterator[StreamChunk]:
        for text in ("a", "b"):
            time.sleep(0.2)
            yield StreamChunk(id="s", delta=text, finish_reason=None, index=0)

    client.stream = slow_stream  # type: ignore[method-assign]
    ticks: list[float] = []

    async def ticker() -> None:
        for _ in range(6):
            ticks.append(time.monotonic())
            await asyncio.sleep(0.05)

    finished: list[float] = []

    async def main() -> list[str]:
        task = asyncio.create_task(ticker())
        await asyncio.sleep(0)
        chunks = [chunk.delta async for chunk in client.astream("hi", model="gpt-4")]
        finished.append(time.monotonic())
        await task
        return chunks

    before = threading.active_count()
    assert asyncio.run(main()) == ["a", "b"]
    # The ticker ran while the stream was waiting (blocking code lets at most one tick through)
    assert sum(tick < finished[0] for tick in ticks) >= 3
    assert threading.active_count() <= before


def test_astream_raises_the_stream_error() -> None:
    client = _client(max_retries=0)
    script = _Script(_http_error(401))

    async def main() -> None:
        async for _ in client.astream("hi", model="gpt-4"):
            pass

    with patch("urllib.request.urlopen", script), pytest.raises(AuthenticationError):
        asyncio.run(main())


# --- finding 13: the Bedrock region ---------------------------------------------------------------


def test_bedrock_reads_aws_region(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.setenv("AWS_REGION", "eu-south-1")
    assert BedrockProvider().region_name == "eu-south-1"
    monkeypatch.delenv("AWS_REGION")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    assert BedrockProvider().region_name == "ap-south-1"


def test_bedrock_without_a_region_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    with pytest.raises(ConfigurationError, match="AWS_REGION"):
        BedrockProvider()


def test_bedrock_takes_the_region_of_its_authenticator(monkeypatch: pytest.MonkeyPatch) -> None:
    from skye.auth.plugins.aws.source import bedrock_authenticator

    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    auth = bedrock_authenticator("eu-central-1", api_key="bedrock-key")
    assert auth.region == "eu-central-1"
    client = BedrockProvider(authenticator=auth)
    assert client.region_name == "eu-central-1" and client._authenticator() is auth


# --- finding 14 / D18: standard key variables -----------------------------------------------------


@pytest.mark.parametrize(
    ("name", "variable", "attribute"),
    [("openai", "OPENAI_API_KEY", "api_key"), ("anthropic", "ANTHROPIC_API_KEY", "api_key")],
)
def test_keys_come_from_the_standard_variable(
    monkeypatch: pytest.MonkeyPatch, name: str, variable: str, attribute: str
) -> None:
    monkeypatch.setenv(variable, "from-env")
    assert getattr(skye.provider(name), attribute) == "from-env"
    monkeypatch.delenv(variable)
    with pytest.raises(ConfigurationError, match=variable):
        skye.provider(name)


def test_embedding_keys_come_from_the_standard_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "from-env")
    monkeypatch.setenv("COHERE_API_KEY", "co-env")
    assert (
        skye.provider("openai", model="text-embedding-3-small", provider_type="embedding").api_key
        == "from-env"
    )
    assert (
        skye.provider("cohere", model="embed-english-v3.0", provider_type="embedding").api_key
        == "co-env"
    )
    monkeypatch.delenv("COHERE_API_KEY")
    with pytest.raises(ConfigurationError, match="COHERE_API_KEY"):
        skye.provider("cohere", model="embed-english-v3.0", provider_type="embedding")


# --- finding 15: Cohere through provider ----------------------------------------------------------


def test_cohere_without_provider_type_is_the_embedding_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COHERE_API_KEY", "co-env")
    embedder = skye.provider("cohere", model="embed-english-v3.0")
    assert type(embedder).__name__ == "CohereEmbeddingProvider"


def test_unknown_provider_does_not_suggest_an_extra() -> None:
    with pytest.raises(ConfigurationError) as caught:
        skye.provider("nope")
    assert "skyeai[" not in str(caught.value)


# --- finding 16: Azure Entra ID -------------------------------------------------------------------


class _Bearer:
    def apply(self, method: str, url: str, headers: Any, body: bytes = b"") -> dict[str, str]:
        return {**headers, "Authorization": "Bearer entra-token"}


def test_azure_accepts_a_token_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    client = AzureOpenAIProvider(
        azure_endpoint="https://r.openai.azure.com",
        api_version="2024-10-21",
        deployment_name="d",
        credentials=_Bearer(),
    )
    script = _Script(CHAT_OK)
    with patch("urllib.request.urlopen", script):
        client.complete("hi", model="d")
    headers = {k.lower(): v for k, v in script.requests[0].header_items()}
    assert headers["authorization"] == "Bearer entra-token" and "api-key" not in headers


def test_azure_reads_its_standard_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "az-env")
    client = AzureOpenAIProvider(
        azure_endpoint="https://r.openai.azure.com", api_version="v", deployment_name="d"
    )
    script = _Script(CHAT_OK)
    with patch("urllib.request.urlopen", script):
        client.complete("hi", model="d")
    headers = {k.lower(): v for k, v in script.requests[0].header_items()}
    assert headers["api-key"] == "az-env"


def test_azure_without_credentials_names_the_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    for name in ("AZURE_OPENAI_API_KEY", "AZURE_TENANT_ID", "AZURE_CLIENT_ID", "IDENTITY_ENDPOINT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AZURE_CONFIG_DIR", str(tmp_path))
    with pytest.raises(ConfigurationError, match="AZURE_OPENAI_API_KEY"):
        AzureOpenAIProvider(
            azure_endpoint="https://r.openai.azure.com", api_version="v", deployment_name="d"
        )


# --- finding 17: a registry as capabilities -------------------------------------------------------


def test_complete_accepts_a_capability_registry() -> None:
    from skye.tools import CapabilityRegistry, capability

    registry = CapabilityRegistry()

    @capability
    def lookup(q: str) -> str:
        """Look up a word."""
        return q

    registry.register(lookup)
    client = _client()
    script = _Script(CHAT_OK)
    with patch("urllib.request.urlopen", script):
        response = client.complete("hi", model="gpt-4", capabilities=registry)
    sent = json.loads(script.requests[0].data)
    assert [tool["function"]["name"] for tool in sent["tools"]] == ["lookup"]
    assert response._capabilities is registry


def test_complete_accepts_any_tool_provider() -> None:
    class Provider:
        async def list_schemas(self, operation: str | None = None) -> list[CapabilitySchema]:
            return [_Capability().get_schema()]

        async def run(self, call: Any, context: Any = None) -> Any:
            raise AssertionError

        async def close(self) -> None:
            pass

    client = AnthropicProvider(api_key="k")
    body = client._transform_request(
        client._resolved(
            CompleteRequest(messages=[UserMessage(content="x")], model="m", capabilities=Provider())
        )
    )
    assert [tool["name"] for tool in body["tools"]] == ["lookup"]


def test_complete_request_has_no_mcp_servers() -> None:
    assert "mcp_servers" not in CompleteRequest.__dataclass_fields__


# --- finding 18: the whole schema is checked ------------------------------------------------------


SCHEMA = OutputSchema(
    "person",
    {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "age": {"type": "integer"},
            "role": {"type": "string", "enum": ["admin", "user"]},
            "tags": {"type": "array", "items": {"type": "string"}},
            "address": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        },
        "required": ["name", "age"],
    },
)


@pytest.mark.parametrize(
    ("reply", "field"),
    [
        ({"name": "A", "age": "3"}, "age"),
        ({"name": "A", "age": True}, "age"),
        ({"name": "A", "age": 3, "role": "root"}, "role"),
        ({"name": "A", "age": 3, "tags": ["x", 1]}, "tags[1]"),
        ({"name": "A", "age": 3, "address": {}}, "address.city"),
        ({"name": "A", "age": 3, "address": {"city": 5}}, "address.city"),
        ({"age": 3}, "name"),
    ],
)
def test_output_schema_replies_are_checked_against_the_whole_schema(
    reply: dict[str, Any], field: str
) -> None:
    with pytest.raises(ValidationError) as caught:
        parse_structured(SCHEMA, json.dumps(reply))
    assert caught.value.details["field"] == field


def test_a_conforming_output_schema_reply_is_returned() -> None:
    reply = {"name": "A", "age": 3, "role": "user", "tags": ["x"], "address": {"city": "Rome"}}
    assert parse_structured(SCHEMA, json.dumps(reply)) == reply


def test_the_key_variables_are_the_ones_of_the_profiles(monkeypatch) -> None:
    """The adapters keep no variable name (task 6.3): they read ``api_key_variables`` of their profile (D18)."""
    from skye.base.api_keys import api_key_variables
    from skye.models.plugins.cohere.embeddings import CohereEmbeddingProvider
    from skye.models.plugins.openai.embeddings import OpenAIEmbeddingProvider

    assert api_key_variables("openai") == ("OPENAI_API_KEY",)
    assert api_key_variables("anthropic") == ("ANTHROPIC_API_KEY",)
    assert api_key_variables("azure") == ("AZURE_OPENAI_API_KEY",)
    assert api_key_variables("cohere") == ("COHERE_API_KEY",)
    for provider_class in (OpenAIProvider, AnthropicProvider, AzureOpenAIProvider):
        assert not hasattr(provider_class, "api_key_env_var")
    monkeypatch.setenv("OPENAI_API_KEY", "ko")
    monkeypatch.setenv("COHERE_API_KEY", "kc")
    assert OpenAIEmbeddingProvider(model="text-embedding-3-small").api_key == "ko"
    assert CohereEmbeddingProvider(model="embed-english-v3.0").api_key == "kc"


def test_the_default_is_three_retries_after_the_first_attempt() -> None:
    """Requirement 9.2: a persistent transient error is called 1 + 3 times, waiting 1, 2 and 4 seconds."""
    client = _client()
    script = _Script(_http_error(503))
    with patch("urllib.request.urlopen", script), pytest.raises(ServerError):
        client.complete("hi", model="gpt-4")
    assert len(script.requests) == 4
    assert client.waits == [1.0, 2.0, 4.0]  # type: ignore[attr-defined]
