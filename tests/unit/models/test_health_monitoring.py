"""Tests for provider health monitoring.

This module tests the health tracking and metrics collection functionality
for LLM and embedding providers.
"""

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from skye.base.completion import CompleteRequest, CompleteResponse, TokenUsage
from skye.base.health import HealthMetrics
from skye.base.messages import UserMessage
from skye.models.base import BaseEmbeddingProvider, BaseModelProvider


class TestHealthMetrics:
    """Test HealthMetrics class."""
    
    def test_record_success(self) -> None:
        """Test recording successful requests."""
        metrics = HealthMetrics()
        
        metrics.record_success(latency_ms=100)
        metrics.record_success(latency_ms=200)
        
        assert metrics.success_count == 2
        assert metrics.failure_count == 0
        assert metrics.total_latency_ms == 300
    
    def test_record_failure(self) -> None:
        """Test recording failed requests."""
        metrics = HealthMetrics()
        
        metrics.record_failure()
        metrics.record_failure()
        
        assert metrics.success_count == 0
        assert metrics.failure_count == 2
    
    def test_get_total_requests(self) -> None:
        """Test getting total request count."""
        metrics = HealthMetrics()
        
        metrics.record_success(latency_ms=100)
        metrics.record_success(latency_ms=200)
        metrics.record_failure()
        
        assert metrics.get_total_requests() == 3
    
    def test_get_success_rate(self) -> None:
        """Test success rate calculation."""
        metrics = HealthMetrics()
        
        # No requests yet
        assert metrics.get_success_rate() == 0.0
        
        # 2 successes, 1 failure
        metrics.record_success(latency_ms=100)
        metrics.record_success(latency_ms=100)
        metrics.record_failure()
        
        assert metrics.get_success_rate() == pytest.approx(2/3)
    
    def test_get_error_rate(self) -> None:
        """Test error rate calculation."""
        metrics = HealthMetrics()
        
        # No requests yet
        assert metrics.get_error_rate() == 0.0
        
        # 2 successes, 1 failure
        metrics.record_success(latency_ms=100)
        metrics.record_success(latency_ms=100)
        metrics.record_failure()
        
        assert metrics.get_error_rate() == pytest.approx(1/3)
    
    def test_get_average_latency_ms(self) -> None:
        """Test average latency calculation."""
        metrics = HealthMetrics()
        
        # No successful requests
        assert metrics.get_average_latency_ms() == 0.0
        
        # Add successful requests
        metrics.record_success(latency_ms=100)
        metrics.record_success(latency_ms=200)
        metrics.record_success(latency_ms=300)
        
        assert metrics.get_average_latency_ms() == pytest.approx(200)
    
    def test_min_max_latency(self) -> None:
        """Test min/max latency tracking."""
        metrics = HealthMetrics()
        
        metrics.record_success(latency_ms=100)
        metrics.record_success(latency_ms=50)
        metrics.record_success(latency_ms=200)
        
        assert metrics.min_latency_ms == 50
        assert metrics.max_latency_ms == 200
    
    def test_get_health_metrics(self) -> None:
        """Test comprehensive health metrics."""
        metrics = HealthMetrics()
        
        metrics.record_success(latency_ms=100)
        metrics.record_success(latency_ms=200)
        metrics.record_failure()
        
        health = metrics.get_health_metrics()
        
        assert health['success_count'] == 2
        assert health['failure_count'] == 1
        assert health['total_requests'] == 3
        assert health['success_rate'] == pytest.approx(2/3)
        assert health['error_rate'] == pytest.approx(1/3)
        assert health['average_latency_ms'] == pytest.approx(150)
        assert health['min_latency_ms'] == 100
        assert health['max_latency_ms'] == 200
        assert health['last_success_time'] is not None
        assert health['last_failure_time'] is not None
    
    def test_reset(self) -> None:
        """Test resetting metrics."""
        metrics = HealthMetrics()
        
        metrics.record_success(latency_ms=100)
        metrics.record_failure()
        
        metrics.reset()
        
        assert metrics.success_count == 0
        assert metrics.failure_count == 0
        assert metrics.total_latency_ms == 0.0
        assert metrics.min_latency_ms == float('inf')
        assert metrics.max_latency_ms == 0.0
        assert metrics.last_success_time is None
        assert metrics.last_failure_time is None
    
    def test_thread_safety(self) -> None:
        """Test thread-safe operations."""
        import threading
        
        metrics = HealthMetrics()
        
        def record_requests() -> None:
            for _ in range(100):
                metrics.record_success(latency_ms=10)
        
        threads = [threading.Thread(target=record_requests) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        
        # Should have 500 successful requests (5 threads * 100 each)
        assert metrics.success_count == 500


class MockModelProvider(BaseModelProvider):
    """Mock model provider for testing."""
    
    def _initialize_client(self) -> MagicMock:
        """Return mock client."""
        return MagicMock()
    
    def _transform_request(self, request: CompleteRequest) -> dict:
        """Transform request."""
        return {"model": request.model, "messages": []}
    
    def _transform_response(self, response: dict) -> CompleteResponse:
        """Transform response."""
        return CompleteResponse(
            id="test-id",
            model="test-model",
            provider="test",
            content="test response",
            finish_reason="stop",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30)
        )
    
    def _transform_stream_chunk(self, chunk: dict) -> dict:
        """Transform stream chunk."""
        return chunk
    
    async def _acall_provider(self, request: dict) -> dict:
        """Call provider."""
        return {"choices": [{"message": {"content": "test"}}]}
    
    async def _acall_provider_stream(self, request: dict):
        """Call provider stream."""
        yield {"choices": [{"delta": {"content": "test"}}]}
    
    def _transform_messages(self, messages: list) -> list[dict]:
        """Transform Skye messages to provider format."""
        return [{"role": msg.role, "content": msg.content} for msg in messages]
    
    def _transform_capabilities(self, capabilities: list) -> list[dict]:
        """Transform Skye capabilities to provider tool format."""
        return [{"name": "mock_tool", "description": "Mock tool"}]
    
    def _extract_capability_calls(self, response: dict) -> list | None:
        """Extract capability calls from provider response."""
        return None  # Mock provider doesn't support capability calls
    
    def format_capability_results(self, results: list[Any]) -> list[dict[str, Any]]:
        """Format capability results for mock provider."""
        return [{"mock_result": "formatted"} for _ in results]
    
    def get_model_info(self) -> dict:
        """Get model info."""
        return {"provider": "test"}


class MockEmbeddingProvider(BaseEmbeddingProvider):
    """Mock embedding provider for testing."""
    
    def _initialize_client(self) -> MagicMock:
        """Return mock client."""
        return MagicMock()
    
    async def _aencode_batch_impl(self, texts: list[str]) -> list[list[float]]:
        """Encode batch."""
        return [[0.1, 0.2, 0.3] for _ in texts]
    
    def get_vector_dimension(self) -> int:
        """Get vector dimension."""
        return 3


class TestModelProviderHealthTracking:
    """Test health tracking in model providers."""
    
    def test_complete_records_success(self) -> None:
        """Test that complete() records successful requests."""
        provider = MockModelProvider()
        request = CompleteRequest(
            messages=[UserMessage(content="test")],
            model="test-model"
        )
        
        response = provider.complete(request)
        
        assert response.content == "test response"
        assert provider.health_metrics.success_count == 1
        assert provider.health_metrics.failure_count == 0
    
    def test_complete_records_failure(self) -> None:
        """Test that complete() records failed requests."""
        provider = MockModelProvider()
        provider._acall_provider = AsyncMock(side_effect=Exception("API error"))
        
        request = CompleteRequest(
            messages=[UserMessage(content="test")],
            model="test-model"
        )
        
        with pytest.raises(Exception):
            provider.complete(request)
        
        assert provider.health_metrics.success_count == 0
        assert provider.health_metrics.failure_count == 1
    
    def test_complete_tracks_latency(self) -> None:
        """Test that complete() tracks latency."""
        provider = MockModelProvider()
        
        # Mock _acall_provider to add delay
        async def slow_call(request: dict) -> dict:
            time.sleep(0.01)  # 10ms delay
            return {"choices": [{"message": {"content": "test"}}]}
        
        provider._acall_provider = slow_call
        
        request = CompleteRequest(
            messages=[UserMessage(content="test")],
            model="test-model"
        )
        
        provider.complete(request)
        
        # Check that latency was recorded (should be at least 10ms)
        assert provider.health_metrics.total_latency_ms >= 10
        assert provider.health_metrics.min_latency_ms >= 10
    
    def test_stream_records_success(self) -> None:
        """Test that stream() records successful requests."""
        provider = MockModelProvider()
        request = CompleteRequest(
            messages=[UserMessage(content="test")],
            model="test-model",
            stream=True
        )
        
        chunks = list(provider.stream(request))
        
        assert len(chunks) > 0
        assert provider.health_metrics.success_count == 1
        assert provider.health_metrics.failure_count == 0
    
    def test_stream_records_failure(self) -> None:
        """Test that stream() records failed requests."""
        provider = MockModelProvider()
        provider._acall_provider_stream = MagicMock(side_effect=Exception("Stream error"))
        
        request = CompleteRequest(
            messages=[UserMessage(content="test")],
            model="test-model",
            stream=True
        )
        
        with pytest.raises(Exception):
            list(provider.stream(request))
        
        assert provider.health_metrics.success_count == 0
        assert provider.health_metrics.failure_count == 1
    
    def test_get_health_metrics(self) -> None:
        """Test get_health_metrics() method."""
        provider = MockModelProvider()
        request = CompleteRequest(
            messages=[UserMessage(content="test")],
            model="test-model"
        )
        
        # Make some requests
        provider.complete(request)
        provider.complete(request)
        
        metrics = provider.get_health_metrics()
        
        assert metrics['success_count'] == 2
        assert metrics['failure_count'] == 0
        assert metrics['total_requests'] == 2
        assert metrics['success_rate'] == 1.0
        assert metrics['error_rate'] == 0.0


class TestEmbeddingProviderHealthTracking:
    """Test health tracking in embedding providers."""
    
    def test_encode_records_success(self) -> None:
        """Test that encode() records successful requests."""
        provider = MockEmbeddingProvider(model="test-model")
        
        vector = provider.encode("test text")
        
        assert len(vector) == 3
        assert provider.health_metrics.success_count == 1
        assert provider.health_metrics.failure_count == 0
    
    def test_encode_records_failure(self) -> None:
        """Test that encode() records failed requests."""
        provider = MockEmbeddingProvider(model="test-model")
        provider._aencode_batch_impl = AsyncMock(side_effect=Exception("Encoding error"))
        
        with pytest.raises(Exception):
            provider.encode("test text")
        
        assert provider.health_metrics.success_count == 0
        assert provider.health_metrics.failure_count == 1
    
    def test_encode_batch_records_success(self) -> None:
        """Test that encode_batch() records successful requests."""
        provider = MockEmbeddingProvider(model="test-model")
        
        vectors = provider.encode_batch(["text1", "text2", "text3"])
        
        assert len(vectors) == 3
        assert provider.health_metrics.success_count == 1
        assert provider.health_metrics.failure_count == 0
    
    def test_encode_batch_records_failure(self) -> None:
        """Test that encode_batch() records failed requests."""
        provider = MockEmbeddingProvider(model="test-model")
        provider._aencode_batch_impl = AsyncMock(side_effect=Exception("Batch error"))
        
        with pytest.raises(Exception):
            provider.encode_batch(["text1", "text2"])
        
        assert provider.health_metrics.success_count == 0
        assert provider.health_metrics.failure_count == 1
    
    @pytest.mark.asyncio
    async def test_aencode_records_success(self) -> None:
        """Test that aencode() records successful requests."""
        provider = MockEmbeddingProvider(model="test-model")
        
        vector = await provider.aencode("test text")
        
        assert len(vector) == 3
        assert provider.health_metrics.success_count == 1
        assert provider.health_metrics.failure_count == 0
    
    @pytest.mark.asyncio
    async def test_aencode_batch_records_success(self) -> None:
        """Test that aencode_batch() records successful requests."""
        provider = MockEmbeddingProvider(model="test-model")
        
        vectors = await provider.aencode_batch(["text1", "text2"])
        
        assert len(vectors) == 2
        assert provider.health_metrics.success_count == 1
        assert provider.health_metrics.failure_count == 0
    
    def test_get_health_metrics(self) -> None:
        """Test get_health_metrics() method."""
        provider = MockEmbeddingProvider(model="test-model")
        
        # Make some requests
        provider.encode("text1")
        provider.encode_batch(["text2", "text3"])
        
        metrics = provider.get_health_metrics()
        
        assert metrics['success_count'] == 2
        assert metrics['failure_count'] == 0
        assert metrics['total_requests'] == 2
        assert metrics['success_rate'] == 1.0
        assert metrics['error_rate'] == 0.0


class TestHealthMetricsIntegration:
    """Integration tests for health metrics."""
    
    def test_mixed_success_and_failure(self) -> None:
        """Test tracking mixed success and failure."""
        provider = MockModelProvider()
        request = CompleteRequest(
            messages=[UserMessage(content="test")],
            model="test-model"
        )
        
        # Successful request
        provider.complete(request)
        
        # Failed request
        provider._acall_provider = AsyncMock(side_effect=Exception("Error"))
        with pytest.raises(Exception):
            provider.complete(request)
        
        # Another successful request
        provider._acall_provider = AsyncMock(return_value={"choices": [{"message": {"content": "test"}}]})
        provider.complete(request)
        
        metrics = provider.get_health_metrics()
        
        assert metrics['success_count'] == 2
        assert metrics['failure_count'] == 1
        assert metrics['total_requests'] == 3
        assert metrics['success_rate'] == pytest.approx(2/3)
        assert metrics['error_rate'] == pytest.approx(1/3)
    
    def test_health_metrics_persistence(self) -> None:
        """Test that health metrics persist across multiple calls."""
        provider = MockModelProvider()
        request = CompleteRequest(
            messages=[UserMessage(content="test")],
            model="test-model"
        )
        
        # Make multiple requests
        for _ in range(5):
            provider.complete(request)
        
        # Check metrics
        metrics1 = provider.get_health_metrics()
        assert metrics1['success_count'] == 5
        
        # Make more requests
        for _ in range(3):
            provider.complete(request)
        
        # Check metrics again
        metrics2 = provider.get_health_metrics()
        assert metrics2['success_count'] == 8
