"""Unit tests for retry logic in providers.

Tests cover:
- Retry decorator functionality
- Exponential backoff timing
- Max retries exceeded
- Successful retry after failures
"""

import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from skye.base.completion import CompleteRequest, CompleteResponse, TokenUsage
from skye.base.exceptions import BadRequestError, ProviderError, RateLimitError
from skye.base.messages import UserMessage
from skye.models.base import BaseModelProvider
from skye.models.utilities.retry import with_retry


class MockProvider(BaseModelProvider):
    """Mock provider for testing retry logic."""

    def __init__(self, **config):
        self.waits: list[float] = []
        super().__init__(retry_sleep=self.waits.append, **config)
        self.call_count = 0
        self.fail_count = 0

    def _initialize_client(self):
        return MagicMock()

    def _transform_request(self, request):
        return {"model": request.model, "messages": []}

    def _transform_response(self, response):
        return CompleteResponse(
            id="test-id",
            model="test-model",
            provider="mock",
            content="test response",
            finish_reason="stop",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

    def _transform_stream_chunk(self, chunk):
        return MagicMock()

    def _transform_messages(self, messages):
        """Transform messages to mock format."""
        return [{"role": m.role, "content": m.content} for m in messages]

    def _transform_capabilities(self, capabilities):
        """Transform capabilities to mock format."""
        return [{"name": c.get_schema().name} for c in capabilities]

    def _extract_capability_calls(self, response):
        """Extract capability calls from mock response."""
        return None
    
    def format_capability_results(self, results: list[Any]) -> list[dict[str, Any]]:
        """Format capability results for mock provider."""
        return [{"mock_result": "formatted"} for _ in results]

    async def _acall_provider(self, request):
        self.call_count += 1
        if self.fail_count > 0:
            self.fail_count -= 1
            raise RateLimitError(
                "Transient error",
                provider="mock",
                status_code=429,
            )
        return MagicMock()

    async def _acall_provider_stream(self, request):
        return
        yield

    def get_model_info(self):
        return {"provider": "mock"}


class TestRetryDecorator:
    """Test the retry decorator."""

    def test_retry_decorator_success_on_first_try(self) -> None:
        """Test that decorator doesn't retry on success."""
        provider = MockProvider()
        request = CompleteRequest(
            messages=[UserMessage(content="test")], model="test-model"
        )

        response = provider.complete(request)

        assert response.content == "test response"
        assert provider.call_count == 1

    def test_retry_decorator_retries_on_failure(self) -> None:
        """A rate limit (a transient error, D104) is retried."""
        provider = MockProvider()
        provider.fail_count = 2  # Fail twice, succeed on third try
        request = CompleteRequest(
            messages=[UserMessage(content="test")], model="test-model"
        )

        response = provider.complete(request)

        assert response.content == "test response"
        assert provider.call_count == 3

    def test_retry_decorator_max_retries_exceeded(self) -> None:
        """Test that decorator raises after max retries exceeded."""
        provider = MockProvider()
        provider.fail_count = 10  # Fail more times than max retries
        request = CompleteRequest(
            messages=[UserMessage(content="test")], model="test-model"
        )

        with pytest.raises(ProviderError):
            provider.complete(request)

        # Should have tried 4 times (initial + 3 retries, Requirement 9.2)
        assert provider.call_count == 4

    def test_a_client_error_is_not_retried(self) -> None:
        """A 4xx other than 429 is raised at once (D104)."""
        provider = MockProvider()

        async def bad_request(request):
            provider.call_count += 1
            raise BadRequestError("bad", provider="mock", status_code=400)

        provider._acall_provider = bad_request  # type: ignore[method-assign]
        with pytest.raises(BadRequestError):
            provider.complete(CompleteRequest(messages=[UserMessage(content="test")], model="test-model"))
        assert provider.call_count == 1 and provider.waits == []

    def test_retry_decorator_exponential_backoff(self) -> None:
        """Test that retry uses exponential backoff."""
        provider = MockProvider()
        provider.fail_count = 1  # Fail once, succeed on second try
        request = CompleteRequest(
            messages=[UserMessage(content="test")], model="test-model"
        )

        response = provider.complete(request)

        assert response.content == "test response"
        # The first wait is the base wait (1 s); it doubles with each retry
        assert provider.waits == [1.0]
        provider.fail_count = 2
        provider.waits.clear()
        provider.complete(request)
        assert provider.waits == [1.0, 2.0]

    def test_retry_decorator_with_custom_params(self) -> None:
        """Test retry decorator with custom parameters."""

        class CustomRetryProvider(BaseModelProvider):
            def __init__(self, **config):
                super().__init__(**config)
                self.call_count = 0

            def _initialize_client(self):
                return MagicMock()

            def _transform_request(self, request):
                return {}

            def _transform_response(self, response):
                return CompleteResponse(
                    id="test",
                    model="test",
                    provider="mock",
                    content="test",
                    finish_reason="stop",
                    usage=TokenUsage(
                        prompt_tokens=10, completion_tokens=5, total_tokens=15
                    ),
                )

            def _transform_stream_chunk(self, chunk):
                return MagicMock()

            def _transform_messages(self, messages):
                """Transform messages to mock format."""
                return [{"role": m.role, "content": m.content} for m in messages]

            def _transform_capabilities(self, capabilities):
                """Transform capabilities to mock format."""
                return [{"name": c.get_schema().name} for c in capabilities]

            def _extract_capability_calls(self, response):
                """Extract capability calls from mock response."""
                return None

            def format_capability_results(self, results: list[Any]) -> list[dict[str, Any]]:
                """Format capability results for mock provider."""
                return [{"mock_result": "formatted"} for _ in results]

            @with_retry(max_retries=2, min_wait=0.1, max_wait=0.2, multiplier=1)
            async def _acall_provider(self, request):
                self.call_count += 1
                if self.call_count < 2:
                    raise RateLimitError("test error", provider="mock", status_code=429)
                return MagicMock()

            async def _acall_provider_stream(self, request):
                return
                yield

            def get_model_info(self):
                return {"provider": "mock"}

        provider = CustomRetryProvider()
        request = CompleteRequest(
            messages=[UserMessage(content="test")], model="test-model"
        )

        # This should succeed after 1 retry
        response = provider.complete(request)
        assert response.content == "test"

    def test_retry_preserves_exception_chain(self) -> None:
        """Test that retry preserves the exception chain."""

        class FailingProvider(BaseModelProvider):
            def _initialize_client(self):
                return MagicMock()

            def _transform_request(self, request):
                return {}

            def _transform_response(self, response):
                return CompleteResponse(
                    id="test",
                    model="test",
                    provider="mock",
                    content="test",
                    finish_reason="stop",
                    usage=TokenUsage(
                        prompt_tokens=10, completion_tokens=5, total_tokens=15
                    ),
                )

            def _transform_stream_chunk(self, chunk):
                return MagicMock()

            def _transform_messages(self, messages):
                """Transform messages to mock format."""
                return [{"role": m.role, "content": m.content} for m in messages]

            def _transform_capabilities(self, capabilities):
                """Transform capabilities to mock format."""
                return [{"name": c.get_schema().name} for c in capabilities]

            def _extract_capability_calls(self, response):
                """Extract capability calls from mock response."""
                return None

            def format_capability_results(self, results: list[Any]) -> list[dict[str, Any]]:
                """Format capability results for mock provider."""
                return [{"mock_result": "formatted"} for _ in results]

            async def _acall_provider(self, request):
                raise ProviderError("original error", provider="mock")

            async def _acall_provider_stream(self, request):
                return
                yield

            def get_model_info(self):
                return {"provider": "mock"}

        provider = FailingProvider()
        request = CompleteRequest(
            messages=[UserMessage(content="test")], model="test-model"
        )

        with pytest.raises(ProviderError) as exc_info:
            provider.complete(request)

        # Check that the exception chain is preserved
        assert exc_info.value.details["provider"] == "mock"
        assert "original error" in str(exc_info.value)


class TestRetryWithStreaming:
    """Test retry logic with streaming."""

    def test_stream_raises_on_failure(self) -> None:
        """Test that stream method raises ProviderError on failure.
        
        Note: The retry decorator wraps the stream method, but the exception
        is caught and re-raised as a new ProviderError in the except block,
        which breaks the retry chain. This is a known limitation of retrying
        generators.
        """

        class StreamingProvider(BaseModelProvider):
            def __init__(self, **config):
                super().__init__(**config)
                self.call_count = 0

            def _initialize_client(self):
                return MagicMock()

            def _transform_request(self, request):
                return {}

            def _transform_response(self, response):
                return CompleteResponse(
                    id="test",
                    model="test",
                    provider="mock",
                    content="test",
                    finish_reason="stop",
                    usage=TokenUsage(
                        prompt_tokens=10, completion_tokens=5, total_tokens=15
                    ),
                )

            def _transform_stream_chunk(self, chunk):
                return MagicMock()

            def _transform_messages(self, messages):
                """Transform messages to mock format."""
                return [{"role": m.role, "content": m.content} for m in messages]

            def _transform_capabilities(self, capabilities):
                """Transform capabilities to mock format."""
                return [{"name": c.get_schema().name} for c in capabilities]

            def _extract_capability_calls(self, response):
                """Extract capability calls from mock response."""
                return None

            def format_capability_results(self, results: list[Any]) -> list[dict[str, Any]]:
                """Format capability results for mock provider."""
                return [{"mock_result": "formatted"} for _ in results]

            async def _acall_provider(self, request):
                return MagicMock()

            async def _acall_provider_stream(self, request):
                self.call_count += 1
                raise ProviderError("stream error", provider="mock")
                yield

            def get_model_info(self):
                return {"provider": "mock"}

        provider = StreamingProvider()
        request = CompleteRequest(
            messages=[UserMessage(content="test")], model="test-model"
        )

        # Stream should raise ProviderError
        with pytest.raises(ProviderError):
            list(provider.stream(request))

        # Only called once because the exception is caught and re-raised
        # before the retry decorator can retry
        assert provider.call_count == 1
