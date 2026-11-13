"""Unit tests for OpenAI embedding provider.

Tests cover:
- Client initialization
- Batch encoding
- Async batch encoding
- Vector dimensions
- Error handling
"""

from unittest.mock import patch

import pytest

from skye.models.plugins.openai.embeddings import OpenAIEmbeddingProvider
from skye.models.utilities.rest import JsonObject

POST = "skye.models.utilities.rest.post_json"
URL = "https://api.openai.com/v1/embeddings"


def _embeddings(*vectors: list[float]) -> JsonObject:
    return JsonObject({"data": [{"index": i, "embedding": v} for i, v in enumerate(vectors)]})


class TestOpenAIEmbeddingProviderInitialization:
    """Test OpenAI embedding provider initialization."""
    
    def test_init_with_required_params(self) -> None:
        """Test initialization with required parameters."""
        provider = OpenAIEmbeddingProvider(
            model="text-embedding-3-small",
            api_key="sk-test"
        )
        assert provider.model == "text-embedding-3-small"
        assert provider.api_key == "sk-test"
    
    def test_init_with_additional_config(self) -> None:
        """Test initialization with additional configuration."""
        provider = OpenAIEmbeddingProvider(
            model="text-embedding-3-large",
            api_key="sk-test",
            organization="org-123"
        )
        assert provider.model == "text-embedding-3-large"
        assert provider.api_key == "sk-test"
        assert provider.config["organization"] == "org-123"
    
    def test_lazy_client_initialization(self) -> None:
        """Construction performs no I/O and holds no vendor client."""
        with patch(POST) as post:
            provider = OpenAIEmbeddingProvider(model="text-embedding-3-small", api_key="sk-test")
            assert provider.client is None
        post.assert_not_called()

    def test_module_imports_no_openai_sdk(self) -> None:
        """The adapter must not import the vendor SDK."""
        import inspect

        import skye.models.plugins.openai.embeddings as mod

        source = inspect.getsource(mod)
        assert "import openai" not in source and "from openai" not in source
        assert "LazyImporter" not in source


class TestOpenAIEmbeddingProviderBatchEncoding:
    """Test batch encoding functionality."""
    
    def test_encode_batch(self) -> None:
        with patch(POST, return_value=_embeddings([0.1, 0.2, 0.3], [0.4, 0.5, 0.6])) as post:
            provider = OpenAIEmbeddingProvider(model="text-embedding-3-small", api_key="sk-test")
            result = provider.encode_batch(["text1", "text2"])

        assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        assert post.call_args.args[0] == URL
        assert post.call_args.args[1] == {"model": "text-embedding-3-small", "input": ["text1", "text2"]}
        assert post.call_args.kwargs["headers"] == {"Authorization": "Bearer sk-test"}
    
    def test_encode_single_text(self) -> None:
        with patch(POST, return_value=_embeddings([0.1, 0.2, 0.3], [0.4, 0.5, 0.6])) as post:
            provider = OpenAIEmbeddingProvider(model="text-embedding-3-small", api_key="sk-test")
            result = provider.encode("hello")

        assert result == [0.1, 0.2, 0.3]
        assert post.call_args.args[0] == URL
        assert post.call_args.args[1] == {"model": "text-embedding-3-small", "input": ["hello"]}
        assert post.call_args.kwargs["headers"] == {"Authorization": "Bearer sk-test"}


class TestOpenAIEmbeddingProviderAsyncEncoding:
    """Test async encoding functionality."""
    
    @pytest.mark.asyncio
    async def test_aencode_batch(self) -> None:
        with patch(POST, return_value=_embeddings([0.1, 0.2, 0.3], [0.4, 0.5, 0.6])) as post:
            provider = OpenAIEmbeddingProvider(model="text-embedding-3-small", api_key="sk-test")
            result = await provider.aencode_batch(["text1", "text2"])

        assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        assert post.call_args.args[0] == URL
        assert post.call_args.args[1] == {"model": "text-embedding-3-small", "input": ["text1", "text2"]}
        assert post.call_args.kwargs["headers"] == {"Authorization": "Bearer sk-test"}
    
    @pytest.mark.asyncio
    async def test_aencode_single_text(self) -> None:
        with patch(POST, return_value=_embeddings([0.1, 0.2, 0.3], [0.4, 0.5, 0.6])) as post:
            provider = OpenAIEmbeddingProvider(model="text-embedding-3-small", api_key="sk-test")
            result = await provider.aencode("hello")

        assert result == [0.1, 0.2, 0.3]
        assert post.call_args.args[0] == URL
        assert post.call_args.args[1] == {"model": "text-embedding-3-small", "input": ["hello"]}
        assert post.call_args.kwargs["headers"] == {"Authorization": "Bearer sk-test"}


class TestOpenAIEmbeddingProviderVectorDimensions:
    """Test vector dimension retrieval."""
    
    def test_get_vector_dimension_small(self) -> None:
        """Test vector dimension for text-embedding-3-small."""
        provider = OpenAIEmbeddingProvider(
            model="text-embedding-3-small",
            api_key="sk-test"
        )
        assert provider.get_vector_dimension() == 1536
    
    def test_get_vector_dimension_large(self) -> None:
        """Test vector dimension for text-embedding-3-large."""
        provider = OpenAIEmbeddingProvider(
            model="text-embedding-3-large",
            api_key="sk-test"
        )
        assert provider.get_vector_dimension() == 3072
    
    def test_get_vector_dimension_ada(self) -> None:
        """Test vector dimension for text-embedding-ada-002."""
        provider = OpenAIEmbeddingProvider(
            model="text-embedding-ada-002",
            api_key="sk-test"
        )
        assert provider.get_vector_dimension() == 1536
    
    def test_get_vector_dimension_unknown_model(self) -> None:
        """Test vector dimension for unknown model."""
        provider = OpenAIEmbeddingProvider(
            model="unknown-model",
            api_key="sk-test"
        )
        with pytest.raises(ValueError, match="Unknown model"):
            provider.get_vector_dimension()
