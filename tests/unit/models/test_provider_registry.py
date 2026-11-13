"""Unit tests for ProviderRegistry."""

from unittest.mock import patch

import pytest

from skye.base.completion import CompleteRequest, CompleteResponse, StreamChunk
from skye.base.exceptions import ConfigurationError
from skye.base.interfaces.model import ModelInterface
from skye.base.interfaces.vector_encoder import VectorEncoderInterface
from skye.base.messages import UserMessage
from skye.base.plugins import Registrar
from skye.models.registry import ProviderRegistry


# Mock provider implementations for testing
class MockModelProvider(ModelInterface):
    """Mock model provider for testing."""

    def __init__(self, api_key: str, **kwargs):
        self.api_key = api_key
        self.config = kwargs

    def complete(self, request: CompleteRequest) -> CompleteResponse:
        from skye.base.completion import TokenUsage

        return CompleteResponse(
            id="test-id",
            model="test-model",
            provider="mock",
            content="Mock response",
            role="assistant",
            finish_reason="stop",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

    def stream(self, request: CompleteRequest):
        yield StreamChunk(id="test-id", delta="Mock ", finish_reason=None, index=0)
        yield StreamChunk(id="test-id", delta="stream", finish_reason="stop", index=0)

    async def acomplete(self, request: CompleteRequest) -> CompleteResponse:
        return self.complete(request)

    async def astream(self, request: CompleteRequest):
        for chunk in self.stream(request):
            yield chunk

    def get_model_info(self) -> dict:
        return {"provider": "mock", "name": "test-model"}


class MockEmbeddingProvider(VectorEncoderInterface):
    """Mock embedding provider for testing."""

    def __init__(self, model: str = "test-embedding", **kwargs):
        self.model = model
        self.config = kwargs

    def encode(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3]

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _ in texts]

    async def aencode(self, text: str) -> list[float]:
        return self.encode(text)

    async def aencode_batch(self, texts: list[str]) -> list[list[float]]:
        return self.encode_batch(texts)

    def get_vector_dimension(self) -> int:
        return 3


class TestProviderRegistry:
    """Test suite for ProviderRegistry."""

    def setup_method(self):
        """Give the registry an empty registrar of its own for each test; the default one, with the built-ins, is untouched."""
        self._private = Registrar()
        self._patch = patch("skye.models.registry._registrar", return_value=self._private)
        self._patch.start()

    def teardown_method(self):
        """Back to the default registrar, so that later tests can create a client."""
        self._patch.stop()

    def test_register_model_provider(self):
        """Test registering a model provider."""
        ProviderRegistry.register_model_provider("mock", MockModelProvider)

        assert self._private.has("provider", "mock", "model")
        assert self._private.get("provider", "mock", "model") == MockModelProvider

    def test_register_embedding_provider(self):
        """Test registering an embedding provider."""
        ProviderRegistry.register_embedding_provider("mock", MockEmbeddingProvider)

        assert self._private.has("provider", "mock", "embedding")
        assert self._private.get("provider", "mock", "embedding") == MockEmbeddingProvider

    def test_get_model_provider_success(self):
        """Test successfully getting a model provider."""
        ProviderRegistry.register_model_provider("mock", MockModelProvider)

        provider = ProviderRegistry.get_model_provider("mock", api_key="test-key")

        assert isinstance(provider, MockModelProvider)
        assert provider.api_key == "test-key"

    def test_get_model_provider_with_config(self):
        """Test getting a model provider with additional config."""
        ProviderRegistry.register_model_provider("mock", MockModelProvider)

        provider = ProviderRegistry.get_model_provider(
            "mock", api_key="test-key", temperature=0.7, max_tokens=100
        )

        assert isinstance(provider, MockModelProvider)
        assert provider.api_key == "test-key"
        assert provider.config["temperature"] == 0.7
        assert provider.config["max_tokens"] == 100

    def test_get_model_provider_not_found(self):
        """Test error when model provider not found."""
        with pytest.raises(ConfigurationError) as exc_info:
            ProviderRegistry.get_model_provider("nonexistent", api_key="test-key")

        error_msg = str(exc_info.value)
        assert "Model provider 'nonexistent' not found" in error_msg
        assert "Available model providers: none" in error_msg
        assert "skyeai[" not in error_msg  # no extra to suggest: the name is not a provider

    def test_get_model_provider_not_found_with_available(self):
        """Test error message includes available providers."""
        ProviderRegistry.register_model_provider("mock1", MockModelProvider)
        ProviderRegistry.register_model_provider("mock2", MockModelProvider)

        with pytest.raises(ConfigurationError) as exc_info:
            ProviderRegistry.get_model_provider("nonexistent", api_key="test-key")

        error_msg = str(exc_info.value)
        assert "Model provider 'nonexistent' not found" in error_msg
        assert "mock1" in error_msg or "mock2" in error_msg

    def test_get_embedding_provider_success(self):
        """Test successfully getting an embedding provider."""
        ProviderRegistry.register_embedding_provider("mock", MockEmbeddingProvider)

        provider = ProviderRegistry.get_embedding_provider("mock", model="test-model")

        assert isinstance(provider, MockEmbeddingProvider)
        assert provider.model == "test-model"

    def test_get_embedding_provider_with_config(self):
        """Test getting an embedding provider with additional config."""
        ProviderRegistry.register_embedding_provider("mock", MockEmbeddingProvider)

        provider = ProviderRegistry.get_embedding_provider(
            "mock", model="test-model", batch_size=32
        )

        assert isinstance(provider, MockEmbeddingProvider)
        assert provider.model == "test-model"
        assert provider.config["batch_size"] == 32

    def test_get_embedding_provider_not_found(self):
        """Test error when embedding provider not found."""
        with pytest.raises(ConfigurationError) as exc_info:
            ProviderRegistry.get_embedding_provider("nonexistent", model="test-model")

        error_msg = str(exc_info.value)
        assert "Embedding provider 'nonexistent' not found" in error_msg
        assert "Available embedding providers: none" in error_msg
        assert "skyeai[" not in error_msg  # no extra to suggest: the name is not a provider

    def test_get_embedding_provider_not_found_with_available(self):
        """Test error message includes available embedding providers."""
        ProviderRegistry.register_embedding_provider("mock1", MockEmbeddingProvider)
        ProviderRegistry.register_embedding_provider("mock2", MockEmbeddingProvider)

        with pytest.raises(ConfigurationError) as exc_info:
            ProviderRegistry.get_embedding_provider("nonexistent", model="test-model")

        error_msg = str(exc_info.value)
        assert "Embedding provider 'nonexistent' not found" in error_msg
        assert "mock1" in error_msg or "mock2" in error_msg

    def test_list_model_providers_empty(self):
        """Test listing model providers when none registered."""
        providers = ProviderRegistry.list_model_providers()

        assert providers == []

    def test_list_model_providers(self):
        """Test listing registered model providers."""
        ProviderRegistry.register_model_provider("mock1", MockModelProvider)
        ProviderRegistry.register_model_provider("mock2", MockModelProvider)

        providers = ProviderRegistry.list_model_providers()

        assert len(providers) == 2
        assert "mock1" in providers
        assert "mock2" in providers

    def test_list_embedding_providers_empty(self):
        """Test listing embedding providers when none registered."""
        providers = ProviderRegistry.list_embedding_providers()

        assert providers == []

    def test_list_embedding_providers(self):
        """Test listing registered embedding providers."""
        ProviderRegistry.register_embedding_provider("mock1", MockEmbeddingProvider)
        ProviderRegistry.register_embedding_provider("mock2", MockEmbeddingProvider)

        providers = ProviderRegistry.list_embedding_providers()

        assert len(providers) == 2
        assert "mock1" in providers
        assert "mock2" in providers

    def test_provider_instantiation_error(self):
        """Test error handling when provider instantiation fails."""

        class BrokenProvider(ModelInterface):
            def __init__(self, api_key: str):
                raise ValueError("Invalid API key format")

            def complete(self, request):
                pass

            def stream(self, request):
                pass

            async def acomplete(self, request):
                pass

            async def astream(self, request):
                pass

            def get_model_info(self):
                pass

        ProviderRegistry.register_model_provider("broken", BrokenProvider)

        with pytest.raises(ConfigurationError) as exc_info:
            ProviderRegistry.get_model_provider("broken", api_key="invalid")

        error_msg = str(exc_info.value)
        assert "Failed to instantiate provider 'broken'" in error_msg
        assert "Invalid API key format" in error_msg

    def test_model_provider_functionality(self):
        """Test that registered model provider works correctly."""
        ProviderRegistry.register_model_provider("mock", MockModelProvider)

        provider = ProviderRegistry.get_model_provider("mock", api_key="test-key")
        request = CompleteRequest(
            messages=[UserMessage(content="Hello")], model="test-model"
        )

        response = provider.complete(request)

        assert response.content == "Mock response"
        assert response.provider == "mock"

    def test_embedding_provider_functionality(self):
        """Test that registered embedding provider works correctly."""
        ProviderRegistry.register_embedding_provider("mock", MockEmbeddingProvider)

        provider = ProviderRegistry.get_embedding_provider("mock", model="test-model")

        vector = provider.encode("test text")

        assert vector == [0.1, 0.2, 0.3]
        assert provider.get_vector_dimension() == 3

    def test_multiple_providers_independent(self):
        """Test that model and embedding registries are independent."""
        ProviderRegistry.register_model_provider("mock", MockModelProvider)
        ProviderRegistry.register_embedding_provider("mock", MockEmbeddingProvider)

        model_providers = ProviderRegistry.list_model_providers()
        embedding_providers = ProviderRegistry.list_embedding_providers()

        assert "mock" in model_providers
        assert "mock" in embedding_providers

        # Both should work independently
        model = ProviderRegistry.get_model_provider("mock", api_key="test-key")
        embedder = ProviderRegistry.get_embedding_provider("mock", model="test-model")

        assert isinstance(model, MockModelProvider)
        assert isinstance(embedder, MockEmbeddingProvider)
