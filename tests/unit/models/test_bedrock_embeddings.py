"""Unit tests for Bedrock embedding provider.

Tests cover:
- Client initialization
- Batch encoding
- Vector dimensions
- No boto3 import
- Error handling
"""

import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from skye.models.plugins.bedrock.embeddings import BedrockEmbeddingProvider
from skye.models.utilities import rest


class TestBedrockEmbeddingProviderInitialization:
    """Test Bedrock embedding provider initialization."""
    
    def test_init_with_required_params(self) -> None:
        """Test initialization with required parameters."""
        provider = BedrockEmbeddingProvider(
            model="amazon.titan-embed-text-v1",
            region_name="us-east-1"
        )
        assert provider.model == "amazon.titan-embed-text-v1"
        assert provider.region_name == "us-east-1"
    
    def test_init_with_additional_config(self) -> None:
        """Test initialization with additional configuration."""
        provider = BedrockEmbeddingProvider(
            model="amazon.titan-embed-text-v2:0",
            region_name="us-west-2",
            profile_name="custom-profile"
        )
        assert provider.model == "amazon.titan-embed-text-v2:0"
        assert provider.region_name == "us-west-2"
        assert provider.config["profile_name"] == "custom-profile"
    
    def test_client_is_none_and_no_boto3(self) -> None:
        provider = BedrockEmbeddingProvider(model="amazon.titan-embed-text-v1", region_name="us-east-1")
        assert provider.client is None
        assert "boto3" not in sys.modules

    def test_source_has_no_boto3_import(self) -> None:
        import skye.models.plugins.bedrock.embeddings as mod

        text = Path(mod.__file__).read_text()
        assert "import boto3" not in text and "LazyImporter" not in text


KEYS = {"aws_access_key_id": "AKIDEXAMPLE", "aws_secret_access_key": "secret"}


class TestBedrockEmbeddingProviderBatchEncoding:
    """Test batch encoding functionality."""

    @patch("skye.models.utilities.rest.post_json")
    def test_encode_batch(self, mock_post: Mock) -> None:
        mock_post.side_effect = [
            rest.JsonObject({"embedding": [0.1, 0.2, 0.3]}),
            rest.JsonObject({"embedding": [0.4, 0.5, 0.6]}),
        ]
        provider = BedrockEmbeddingProvider(model="amazon.titan-embed-text-v2:0", region_name="us-east-1", **KEYS)

        result = provider.encode_batch(["text1", 'te"xt2'])

        assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        assert mock_post.call_count == 2
        first, second = mock_post.call_args_list
        assert first.args[0] == (
            "https://bedrock-runtime.us-east-1.amazonaws.com/model/amazon.titan-embed-text-v2%3A0/invoke"
        )
        assert first.args[1] == {"inputText": "text1"}
        assert second.args[1] == {"inputText": 'te"xt2'}
        assert first.kwargs["authenticator"] is not None

    @patch("skye.models.utilities.rest.post_json")
    def test_encode_single_text(self, mock_post: Mock) -> None:
        mock_post.return_value = rest.JsonObject({"embedding": [0.1, 0.2, 0.3]})
        provider = BedrockEmbeddingProvider(model="amazon.titan-embed-text-v1", region_name="us-east-1", **KEYS)

        assert provider.encode("hello") == [0.1, 0.2, 0.3]
        mock_post.assert_called_once()


class TestBedrockEmbeddingProviderVectorDimensions:
    """Test vector dimension retrieval."""
    
    def test_get_vector_dimension_v1(self) -> None:
        """Test vector dimension for amazon.titan-embed-text-v1."""
        provider = BedrockEmbeddingProvider(
            model="amazon.titan-embed-text-v1",
            region_name="us-east-1"
        )
        assert provider.get_vector_dimension() == 1536
    
    def test_get_vector_dimension_v2(self) -> None:
        """Test vector dimension for amazon.titan-embed-text-v2:0."""
        provider = BedrockEmbeddingProvider(
            model="amazon.titan-embed-text-v2:0",
            region_name="us-east-1"
        )
        assert provider.get_vector_dimension() == 1024
    
    def test_get_vector_dimension_unknown_model(self) -> None:
        """Test vector dimension for unknown model."""
        provider = BedrockEmbeddingProvider(
            model="unknown-model",
            region_name="us-east-1"
        )
        with pytest.raises(ValueError, match="Unknown model"):
            provider.get_vector_dimension()
