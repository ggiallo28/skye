"""A provider writes the async side only; ``complete`` and ``stream`` are derived from it
(Requirement 56.13, task 20.2)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

import pytest

from skye.base.completion import CompleteResponse, StreamChunk, TokenUsage
from skye.base.exceptions import ProviderError, RateLimitError
from skye.models import BaseModelProvider
from skye.models.plugins.bedrock.provider import BedrockProvider
from skye.models.plugins.google.provider import GoogleProvider
from skye.models.utilities.anthropic_compatible.provider import AnthropicCompatibleProvider
from skye.models.utilities.openai_compatible.provider import OpenAICompatibleProvider


class AsyncOnly(BaseModelProvider):
    """What a plugin author writes: the request and response shapes, and two async transports."""

    def __init__(self, **config: Any) -> None:
        self.waits: list[float] = []
        super().__init__(retry_sleep=self.waits.append, **config)
        self.calls = 0
        self.stream_closed = False
        self.fail_first = 0
        self.words = ["a", "b", "c"]

    def _initialize_client(self) -> Any:
        return None

    def _transform_request(self, request: Any) -> dict[str, Any]:
        return {"model": request.model}

    def _transform_response(self, response: Any) -> CompleteResponse:
        usage = TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2)
        return CompleteResponse(
            model="m", provider="x", content=response["text"], finish_reason="stop", usage=usage
        )

    def _transform_stream_chunk(self, chunk: Any) -> StreamChunk:
        return StreamChunk(id="s", delta=chunk, finish_reason=None, index=0)

    def _transform_messages(self, messages: list[Any]) -> list[dict[str, Any]]:
        return []

    def _transform_capabilities(self, capabilities: list[Any]) -> list[dict[str, Any]]:
        return []

    def _extract_capability_calls(self, response: Any) -> list[Any] | None:
        return None

    def format_capability_results(self, results: list[Any]) -> list[dict[str, Any]]:
        return []

    def get_model_info(self) -> dict[str, Any]:
        return {"provider": "x"}

    async def _acall_provider(self, request: dict[str, Any]) -> Any:
        self.calls += 1
        if self.fail_first:
            self.fail_first -= 1
            raise RateLimitError("slow down", provider="x", status_code=429)
        await asyncio.sleep(0)
        return {"text": "hello"}

    async def _acall_provider_stream(self, request: dict[str, Any]) -> AsyncGenerator[Any, None]:
        self.calls += 1
        if self.fail_first:
            self.fail_first -= 1
            raise RateLimitError("slow down", provider="x", status_code=429)
        try:
            for word in self.words:
                await asyncio.sleep(0)
                yield word
        finally:
            self.stream_closed = True


def test_the_sync_methods_are_derived_from_the_async_ones() -> None:
    client = AsyncOnly()
    assert client.complete("hi", model="m").content == "hello"
    assert "".join(chunk.delta for chunk in client.stream("hi", model="m")) == "abc"
    assert asyncio.run(client.acomplete("hi", model="m")).content == "hello"


def test_complete_works_inside_a_running_loop() -> None:
    client = AsyncOnly()

    async def main() -> str:
        return client.complete("hi", model="m").content  # blocks the loop, but does not fail

    assert asyncio.run(main()) == "hello"


def test_a_transient_error_is_retried_before_the_first_chunk_and_the_wait_is_injected() -> None:
    client = AsyncOnly()
    client.fail_first = 2
    assert client.complete("hi", model="m").content == "hello"
    assert client.calls == 3 and len(client.waits) == 2
    client.fail_first = 1
    assert "".join(chunk.delta for chunk in client.stream("hi", model="m")) == "abc"
    assert len(client.waits) == 3


def test_the_default_wait_is_asyncio_sleep() -> None:
    client = AsyncOnly()
    client.retry_sleep = None
    client.retry_base_wait = 0.0
    client.fail_first = 1
    assert client.complete("hi", model="m").content == "hello"


def test_an_error_after_retries_reaches_the_caller_unchanged() -> None:
    client = AsyncOnly(max_retries=1)
    client.fail_first = 5
    with pytest.raises(RateLimitError):
        client.complete("hi", model="m")
    assert client.calls == 2


def test_closing_a_sync_stream_early_closes_the_transport() -> None:
    client = AsyncOnly()
    client.words = ["a"] * 50
    chunks = client.stream("hi", model="m")
    next(chunks)
    chunks.close()  # type: ignore[attr-defined]
    assert client.stream_closed


def test_an_error_in_the_stream_reaches_the_caller() -> None:
    class Broken(AsyncOnly):
        async def _acall_provider_stream(
            self, request: dict[str, Any]
        ) -> AsyncGenerator[Any, None]:
            yield "a"
            raise ProviderError("dropped", provider="x")

    with pytest.raises(ProviderError):
        list(Broken().stream("hi", model="m"))


@pytest.mark.parametrize(
    "cls", [OpenAICompatibleProvider, AnthropicCompatibleProvider, BedrockProvider, GoogleProvider]
)
def test_a_built_in_adapter_keeps_only_the_async_transport(cls: type) -> None:
    own = set(vars(cls))
    assert {"_acall_provider", "_acall_provider_stream"} <= own
    assert not own & {
        "complete",
        "stream",
        "acomplete",
        "astream",
        "_call_provider",
        "_call_provider_stream",
    }


def test_the_base_class_has_no_parallel_sync_path() -> None:
    gone = [
        "_call_provider",
        "_call_provider_stream",
        "_complete_once",
        "_stream_once",
        "_complete_with_retry",
        "_stream_with_retry",
        "_select_with_router",
    ]
    assert not [name for name in gone if hasattr(BaseModelProvider, name)]
