"""Runnable Port conformance for the LLM model adapters (structure task 4.3).

Verifies that the consolidated LLM adapters satisfy the ``Runnable`` Port
(``base/interfaces/runnable.py``) so a model is usable anywhere a ``Runnable``
is accepted. The Port is one input -> one output: ``async invoke(input) -> output``.

These tests are structural / behavior-preserving: ``invoke`` must delegate to
``acomplete`` and return exactly what ``acomplete`` returns, without touching the
existing completion paths.

_Requirements: 4.1, 4.8, 12.2, 12.7_
"""

from typing import Any

import pytest

from skye.base.completion import CompleteRequest, CompleteResponse, TokenUsage
from skye.base.interfaces.runnable import Runnable
from skye.base.messages import UserMessage
from skye.models import (
    AnthropicProvider,
    AzureOpenAIProvider,
    BedrockProvider,
    GoogleProvider,
    OpenAIProvider,
)


def _make_provider(cls: type) -> Any:
    """Construct each adapter with minimal, no-network config.

    Clients are lazily initialized, so no credentials are exercised by
    construction or by the ``invoke`` delegation checks below.
    """
    if cls is OpenAIProvider:
        return OpenAIProvider(api_key="test-key")
    if cls is AzureOpenAIProvider:
        return AzureOpenAIProvider(
            azure_endpoint="https://example.openai.azure.com/",
            api_key="test-key",
            api_version="2024-02-15-preview",
            deployment_name="gpt-4",
        )
    if cls is AnthropicProvider:
        return AnthropicProvider(api_key="test-key")
    if cls is BedrockProvider:
        return BedrockProvider(region_name="us-east-1")
    if cls is GoogleProvider:
        return GoogleProvider(project_id="test-project")
    raise AssertionError(f"unhandled provider class: {cls}")


ADAPTER_CLASSES = [
    OpenAIProvider,
    AzureOpenAIProvider,
    AnthropicProvider,
    BedrockProvider,
    GoogleProvider,
]


@pytest.mark.parametrize("cls", ADAPTER_CLASSES)
def test_adapter_is_runnable_instance(cls: type) -> None:
    """Each LLM adapter conforms to the runtime-checkable Runnable Protocol."""
    provider = _make_provider(cls)
    assert isinstance(provider, Runnable)


@pytest.mark.parametrize("cls", ADAPTER_CLASSES)
def test_adapter_exposes_async_invoke(cls: type) -> None:
    """Each adapter exposes a callable ``invoke`` (one input -> one output)."""
    provider = _make_provider(cls)
    assert callable(getattr(provider, "invoke", None))


@pytest.mark.asyncio
async def test_invoke_delegates_to_acomplete() -> None:
    """``invoke(request)`` returns exactly what ``acomplete(request)`` returns.

    Confirms the Runnable entry point is a thin, behavior-preserving delegation
    to the existing completion path rather than a new code path.
    """
    provider = OpenAIProvider(api_key="test-key")

    request = CompleteRequest(
        messages=[UserMessage(content="Hello")],
        model="gpt-4",
    )

    sentinel = CompleteResponse(
        id="resp-1",
        model="gpt-4",
        provider="openai",
        content="hi",
        finish_reason="stop",
        usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
    )

    seen: dict[str, Any] = {}

    async def fake_acomplete(req: CompleteRequest) -> CompleteResponse:
        seen["request"] = req
        return sentinel

    provider.acomplete = fake_acomplete  # type: ignore[method-assign,assignment]

    result = await provider.invoke(request)

    assert result is sentinel
    assert seen["request"] is request
