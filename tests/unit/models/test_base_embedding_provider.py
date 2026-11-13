"""Unit tests for BaseEmbeddingProvider."""

from typing import Any

import pytest

from skye.models.base import BaseEmbeddingProvider


class MockEmbeddingProvider(BaseEmbeddingProvider):
    """Mock embedding provider for testing."""
    
    def __init__(self, model: str = "test-embedding", **config):
        super().__init__(model=model, **config)
        self.client_initialized = False
        self.dimension = config.get("dimension", 1536)
    
    def _initialize_client(self) -> Any:
        """Initialize mock client."""
        self.client_initialized = True
        return {"mock": "embedding_client"}
    
    async def _aencode_batch_impl(self, texts: list[str]) -> list[list[float]]:
        """Mock batch encoding implementation."""
        # Return mock embeddings (simplified for testing)
        return [[float(i) for i in range(self.dimension)] for _ in texts]
    
    def get_vector_dimension(self) -> int:
        """Return mock dimension."""
        return self.dimension


def test_embedding_provider_initialization():
    """Test that BaseEmbeddingProvider initializes correctly."""
    provider = MockEmbeddingProvider(
        model="test-model",
        api_key="test_key",
        dimension=768
    )
    
    assert provider.model == "test-model"
    assert provider.config["api_key"] == "test_key"
    assert provider.config["dimension"] == 768
    assert provider._client is None


def test_lazy_client_initialization():
    """Test that client is lazily initialized."""
    provider = MockEmbeddingProvider()
    
    # Client should not be initialized yet
    assert provider._client is None
    assert not provider.client_initialized
    
    # Access client property
    client = provider.client
    
    # Client should now be initialized
    assert client == {"mock": "embedding_client"}
    assert provider.client_initialized
    assert provider._client is not None
    
    # Accessing again should return same client
    client2 = provider.client
    assert client2 is client



def test_encode_single_text():
    """Test encoding single text."""
    provider = MockEmbeddingProvider(dimension=128)
    
    vector = provider.encode("Hello world")
    
    assert isinstance(vector, list)
    assert len(vector) == 128
    assert all(isinstance(v, float) for v in vector)


def test_encode_batch():
    """Test encoding multiple texts."""
    provider = MockEmbeddingProvider(dimension=256)
    texts = ["Hello", "World", "Test"]
    
    vectors = provider.encode_batch(texts)
    
    assert isinstance(vectors, list)
    assert len(vectors) == 3
    assert all(len(v) == 256 for v in vectors)
    assert all(isinstance(val, float) for v in vectors for val in v)


def test_encode_uses_encode_batch():
    """Test that encode() uses encode_batch() internally."""
    provider = MockEmbeddingProvider(dimension=64)
    
    # encode() should call encode_batch() with a single-item list
    vector = provider.encode("Test")
    batch_result = provider.encode_batch(["Test"])
    
    assert vector == batch_result[0]


@pytest.mark.asyncio
async def test_aencode_single_text():
    """Test async encoding single text."""
    provider = MockEmbeddingProvider(dimension=128)
    
    vector = await provider.aencode("Hello world")
    
    assert isinstance(vector, list)
    assert len(vector) == 128
    assert all(isinstance(v, float) for v in vector)


@pytest.mark.asyncio
async def test_aencode_batch_default_implementation():
    """Test that default aencode_batch uses sync version."""
    provider = MockEmbeddingProvider(dimension=256)
    texts = ["Hello", "World", "Test"]
    
    vectors = await provider.aencode_batch(texts)
    
    assert isinstance(vectors, list)
    assert len(vectors) == 3
    assert all(len(v) == 256 for v in vectors)


@pytest.mark.asyncio
async def test_aencode_uses_aencode_batch():
    """Test that aencode() uses aencode_batch() internally."""
    provider = MockEmbeddingProvider(dimension=64)
    
    # aencode() should call aencode_batch() with a single-item list
    vector = await provider.aencode("Test")
    batch_result = await provider.aencode_batch(["Test"])
    
    assert vector == batch_result[0]


def test_get_vector_dimension():
    """Test getting vector dimension."""
    provider = MockEmbeddingProvider(dimension=512)
    
    dimension = provider.get_vector_dimension()
    
    assert dimension == 512


def test_different_dimensions():
    """Test providers with different dimensions."""
    provider_small = MockEmbeddingProvider(dimension=384)
    provider_large = MockEmbeddingProvider(dimension=1536)
    
    assert provider_small.get_vector_dimension() == 384
    assert provider_large.get_vector_dimension() == 1536
    
    vector_small = provider_small.encode("Test")
    vector_large = provider_large.encode("Test")
    
    assert len(vector_small) == 384
    assert len(vector_large) == 1536
