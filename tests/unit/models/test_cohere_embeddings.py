"""Unit tests for Cohere embedding provider.

Tests cover:
- Client initialization
- Batch encoding
- Vector dimensions
- Error handling
"""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from skye.models.plugins.cohere.embeddings import CohereEmbeddingProvider
from skye.models.utilities.rest import JsonObject


class TestCohereEmbeddingProviderInitialization:
    """Test Cohere embedding provider initialization."""
    
    def test_init_with_required_params(self) -> None:
        """Test initialization with required parameters."""
        provider = CohereEmbeddingProvider(
            model="embed-english-v3.0",
            api_key="cohere-key"
        )
        assert provider.model == "embed-english-v3.0"
        assert provider.api_key == "cohere-key"
    
    def test_init_with_additional_config(self) -> None:
        """Test initialization with additional configuration."""
        provider = CohereEmbeddingProvider(
            model="embed-multilingual-v3.0",
            api_key="cohere-key",
            timeout=30
        )
        assert provider.model == "embed-multilingual-v3.0"
        assert provider.api_key == "cohere-key"
        assert provider.config["timeout"] == 30
    
    def test_client_is_lazy_and_sdk_free(self) -> None:
        """The client initialises without importing any vendor SDK."""
        provider = CohereEmbeddingProvider(model="embed-english-v3.0", api_key="cohere-key")
        assert provider.client is None


def _response(vectors: list[list[float]]) -> JsonObject:
    return JsonObject({"embeddings": {"float": vectors}})


class TestCohereEmbeddingProviderBatchEncoding:
    """Test batch encoding functionality."""

    @patch("skye.models.utilities.rest.post_json")
    def test_encode_batch(self, mock_post: Mock) -> None:
        mock_post.return_value = _response([[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])
        provider = CohereEmbeddingProvider(model="embed-english-v3.0", api_key="cohere-key")

        result = provider.encode_batch(["text1", "text2"])

        assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        args, kwargs = mock_post.call_args
        assert args[0] == "https://api.cohere.com/v2/embed"
        assert args[1] == {
            "model": "embed-english-v3.0",
            "texts": ["text1", "text2"],
            "input_type": "search_document",
            "embedding_types": ["float"],
        }
        assert kwargs["headers"] == {"Authorization": "Bearer cohere-key"}

    @patch("skye.models.utilities.rest.post_json")
    def test_encode_single_text(self, mock_post: Mock) -> None:
        mock_post.return_value = _response([[0.1, 0.2, 0.3]])
        provider = CohereEmbeddingProvider(model="embed-english-v3.0", api_key="cohere-key")

        assert provider.encode("hello") == [0.1, 0.2, 0.3]
        assert mock_post.call_args.args[1]["texts"] == ["hello"]


class TestCohereNoVendorSdk:
    def test_module_imports_no_cohere_sdk(self) -> None:
        import ast

        import skye.models.plugins.cohere.embeddings as mod

        tree = ast.parse(Path(mod.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(a.name.split(".")[0] != "cohere" for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] != "cohere"
        assert "LazyImporter" not in Path(mod.__file__).read_text()


class TestCohereEmbeddingProviderVectorDimensions:
    """Test vector dimension retrieval."""
    
    def test_get_vector_dimension_english_v3(self) -> None:
        """Test vector dimension for embed-english-v3.0."""
        provider = CohereEmbeddingProvider(
            model="embed-english-v3.0",
            api_key="cohere-key"
        )
        assert provider.get_vector_dimension() == 1024
    
    def test_get_vector_dimension_english_light_v3(self) -> None:
        """Test vector dimension for embed-english-light-v3.0."""
        provider = CohereEmbeddingProvider(
            model="embed-english-light-v3.0",
            api_key="cohere-key"
        )
        assert provider.get_vector_dimension() == 384
    
    def test_get_vector_dimension_multilingual_v3(self) -> None:
        """Test vector dimension for embed-multilingual-v3.0."""
        provider = CohereEmbeddingProvider(
            model="embed-multilingual-v3.0",
            api_key="cohere-key"
        )
        assert provider.get_vector_dimension() == 1024
    
    def test_get_vector_dimension_unknown_model(self) -> None:
        """Test vector dimension for unknown model."""
        provider = CohereEmbeddingProvider(
            model="unknown-model",
            api_key="cohere-key"
        )
        with pytest.raises(ValueError, match="Unknown model"):
            provider.get_vector_dimension()
