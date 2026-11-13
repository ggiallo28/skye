"""Unit tests for BaseModelProvider."""

from datetime import datetime, timezone
from collections.abc import AsyncGenerator
from typing import Any

import pytest

from skye.base.completion import CompleteRequest, CompleteResponse, StreamChunk, TokenUsage
from skye.base.exceptions import ProviderError
from skye.base.messages import UserMessage
from skye.models.base import BaseModelProvider


class MockProvider(BaseModelProvider):
    """Mock provider for testing BaseModelProvider."""
    
    def __init__(self, **config):
        super().__init__(**config)
        self.client_initialized = False
        self.should_fail = config.get("should_fail", False)
        self.fail_on_stream = config.get("fail_on_stream", False)
    
    def _initialize_client(self) -> Any:
        """Initialize mock client."""
        self.client_initialized = True
        return {"mock": "client"}
    
    def _transform_request(self, request: CompleteRequest) -> dict[str, Any]:
        """Transform request to mock format."""
        return {
            "model": request.model,
            "messages": [{"role": "user", "content": "test"}],
            "temperature": request.temperature
        }
    
    def _transform_response(self, response: Any) -> CompleteResponse:
        """Transform mock response to CompleteResponse."""
        return CompleteResponse(
            id="test_id",
            model="test_model",
            provider="mock",
            content=response["content"],
            finish_reason="stop",
            usage=TokenUsage(
                prompt_tokens=10,
                completion_tokens=20,
                total_tokens=30
            ),
            created_at=datetime.now(timezone.utc)
        )
    
    def _transform_stream_chunk(self, chunk: Any) -> StreamChunk:
        """Transform mock stream chunk to StreamChunk."""
        return StreamChunk(
            id="test_stream",
            delta=chunk.get("delta", ""),
            finish_reason=chunk.get("finish_reason"),
            index=0
        )
    
    async def _acall_provider(self, request: dict[str, Any]) -> Any:
        """Make mock provider API call."""
        if self.should_fail:
            raise Exception("Mock provider failure")
        return {"content": "Mock response"}
    
    async def _acall_provider_stream(self, request: dict[str, Any]) -> AsyncGenerator[Any, None]:
        """Make mock streaming provider API call."""
        if self.fail_on_stream:
            raise Exception("Mock stream failure")
        yield {"delta": "Mock "}
        yield {"delta": "stream "}
        yield {"delta": "response", "finish_reason": "stop"}
    
    def _transform_messages(self, messages: list[Any]) -> list[dict[str, Any]]:
        """Transform Skye messages to mock format."""
        return [{"role": msg.role, "content": msg.content} for msg in messages]
    
    def _transform_capabilities(self, capabilities: list[Any]) -> list[dict[str, Any]]:
        """Transform Skye capabilities to mock tool format."""
        return [{"name": "mock_tool", "description": "Mock tool"}]
    
    def _extract_capability_calls(self, response: Any) -> list[Any] | None:
        """Extract capability calls from mock response."""
        return None  # Mock provider doesn't support capability calls
    
    def format_capability_results(self, results: list[Any]) -> list[dict[str, Any]]:
        """Format capability results for mock provider."""
        return [{"mock_result": "formatted"} for _ in results]
    
    def _transform_stream_chunk(self, chunk: Any) -> StreamChunk:
        """Transform mock chunk to StreamChunk."""
        return StreamChunk(
            id="stream_id",
            delta=chunk["delta"],
            finish_reason=chunk.get("finish_reason"),
            index=chunk.get("index", 0)
        )
    
    async def _acall_provider(self, request: dict[str, Any]) -> Any:
        """Mock provider call."""
        if self.should_fail:
            raise ValueError("Mock provider error")
        return {"content": "Mock response"}
    
    async def _acall_provider_stream(self, request: dict[str, Any]) -> AsyncGenerator[Any, None]:
        """Mock streaming provider call."""
        if self.fail_on_stream:
            raise ValueError("Mock streaming error")
        
        yield {"delta": "Hello", "index": 0}
        yield {"delta": " ", "index": 1}
        yield {"delta": "world", "index": 2}
        yield {"delta": "", "finish_reason": "stop", "index": 3}
    
    def get_model_info(self) -> dict[str, Any]:
        """Return mock model info."""
        return {
            "provider": "mock",
            "supports_streaming": True,
            "supports_function_calling": False
        }


def test_base_provider_initialization():
    """Test that BaseModelProvider initializes correctly."""
    provider = MockProvider(api_key="test_key", custom_param="value")
    
    assert provider.config["api_key"] == "test_key"
    assert provider.config["custom_param"] == "value"
    assert provider._client is None


def test_lazy_client_initialization():
    """Test that client is lazily initialized."""
    provider = MockProvider()
    
    # Client should not be initialized yet
    assert provider._client is None
    assert not provider.client_initialized
    
    # Access client property
    client = provider.client
    
    # Client should now be initialized
    assert client == {"mock": "client"}
    assert provider.client_initialized
    assert provider._client is not None
    
    # Accessing again should return same client
    client2 = provider.client
    assert client2 is client



def test_complete_success():
    """Test successful completion."""
    provider = MockProvider()
    request = CompleteRequest(
        messages=[UserMessage(content="Hello")],
        model="test_model",
        temperature=0.7
    )
    
    response = provider.complete(request)
    
    assert isinstance(response, CompleteResponse)
    assert response.content == "Mock response"
    assert response.model == "test_model"
    assert response.provider == "mock"
    assert response.finish_reason == "stop"
    assert response.usage.total_tokens == 30


def test_complete_error_wrapping():
    """Test that errors are wrapped in ProviderError."""
    provider = MockProvider(should_fail=True)
    request = CompleteRequest(
        messages=[UserMessage(content="Hello")],
        model="test_model"
    )
    
    with pytest.raises(ProviderError) as exc_info:
        provider.complete(request)
    
    error = exc_info.value
    assert "Provider call failed" in error.message
    assert error.details["provider"] == "mock"
    assert error.details["error_type"] == "ValueError"
    assert "Mock provider error" in error.details["original_error"]


def test_stream_success():
    """Test successful streaming."""
    provider = MockProvider()
    request = CompleteRequest(
        messages=[UserMessage(content="Hello")],
        model="test_model",
        stream=True
    )
    
    chunks = list(provider.stream(request))
    
    assert len(chunks) == 4
    assert chunks[0].delta == "Hello"
    assert chunks[1].delta == " "
    assert chunks[2].delta == "world"
    assert chunks[3].delta == ""
    assert chunks[3].finish_reason == "stop"


def test_stream_error_wrapping():
    """Test that streaming errors are wrapped in ProviderError."""
    provider = MockProvider(fail_on_stream=True)
    request = CompleteRequest(
        messages=[UserMessage(content="Hello")],
        model="test_model",
        stream=True
    )
    
    with pytest.raises(ProviderError) as exc_info:
        list(provider.stream(request))
    
    error = exc_info.value
    assert "Provider streaming failed" in error.message
    assert error.details["provider"] == "mock"
    assert error.details["error_type"] == "ValueError"



@pytest.mark.asyncio
async def test_acomplete_default_implementation():
    """Test that default acomplete uses sync version."""
    provider = MockProvider()
    request = CompleteRequest(
        messages=[UserMessage(content="Hello")],
        model="test_model"
    )
    
    response = await provider.acomplete(request)
    
    assert isinstance(response, CompleteResponse)
    assert response.content == "Mock response"


@pytest.mark.asyncio
async def test_astream_default_implementation():
    """Test that default astream uses sync version."""
    provider = MockProvider()
    request = CompleteRequest(
        messages=[UserMessage(content="Hello")],
        model="test_model",
        stream=True
    )
    
    chunks = []
    async for chunk in provider.astream(request):
        chunks.append(chunk)
    
    assert len(chunks) == 4
    assert chunks[0].delta == "Hello"


def test_get_model_info():
    """Test get_model_info returns correct metadata."""
    provider = MockProvider()
    
    info = provider.get_model_info()
    
    assert info["provider"] == "mock"
    assert info["supports_streaming"] is True
    assert info["supports_function_calling"] is False


def test_transform_request():
    """Test request transformation."""
    provider = MockProvider()
    request = CompleteRequest(
        messages=[UserMessage(content="Hello")],
        model="gpt-4",
        temperature=0.8
    )
    
    transformed = provider._transform_request(request)
    
    assert transformed["model"] == "gpt-4"
    assert transformed["temperature"] == 0.8
    assert "messages" in transformed
