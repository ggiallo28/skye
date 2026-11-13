"""AWS Bedrock embedding provider implementation.

This module provides the BedrockEmbeddingProvider class for generating embeddings
using AWS Bedrock's embedding models.

Example:
    >>> from skye.models import BedrockEmbeddingProvider
    >>>
    >>> embedder = BedrockEmbeddingProvider(
    ...     model="amazon.titan-embed-text-v1",
    ...     region_name="us-east-1"
    ... )
    >>> vector = embedder.encode("Hello, world!")
    >>> vectors = embedder.encode_batch(["text1", "text2"])
"""

import asyncio
from typing import Any

from skye.models.base import BaseEmbeddingProvider
from skye.models.utilities import rest
from skye.models.utilities.credentials import resolve_aws_region


class BedrockEmbeddingProvider(BaseEmbeddingProvider):
    """AWS Bedrock embedding provider implementation.

    Supports AWS Bedrock's embedding models:
    - amazon.titan-embed-text-v1 (1536 dimensions)
    - amazon.titan-embed-text-v2:0 (1024 dimensions)

    Uses the built-in stdlib REST adapter (SigV4 or Bedrock API key); no AWS SDK.

    Example:
        >>> embedder = BedrockEmbeddingProvider(
        ...     model="amazon.titan-embed-text-v1",
        ...     region_name="us-east-1"
        ... )
        >>> vector = embedder.encode("Hello")
        >>> vectors = embedder.encode_batch(["text1", "text2"])
    """

    def __init__(self, model: str, region_name: str | None = None, **config: Any) -> None:
        """Initialize Bedrock embedding provider.

        Args:
            model: Model identifier (e.g., 'amazon.titan-embed-text-v1')
            region_name: AWS region name; ``AWS_REGION``, then ``AWS_DEFAULT_REGION`` when omitted
            **config: Additional configuration parameters (e.g., profile_name)

        Raises:
            ConfigurationError: No region is given or found.
        """
        region = resolve_aws_region(region_name)
        super().__init__(model=model, region_name=region, **config)
        self.region_name = region

    def _initialize_client(self) -> Any:
        """No vendor client: requests go through the stdlib REST transport."""
        return None

    def _authenticator(self) -> Any:
        if getattr(self, "_auth", None) is None:
            from skye.auth.plugins.aws import bedrock_authenticator

            self._auth = bedrock_authenticator(
                self.region_name,
                api_key=self.config.get("api_key"),
                profile_name=self.config.get("profile_name"),
                access_key=self.config.get("aws_access_key_id"),
                secret_key=self.config.get("aws_secret_access_key"),
                session_token=self.config.get("aws_session_token"),
            )
        return self._auth

    async def _aencode_batch_impl(self, texts: list[str]) -> list[list[float]]:
        """Encode texts via ``/model/{id}/invoke`` (one request per text, as Titan requires; each
        blocking call runs in a worker thread)."""
        import urllib.parse

        host = (
            self.config.get("endpoint_url")
            or f"https://bedrock-runtime.{self.region_name}.amazonaws.com"
        )
        url = f"{host}/model/{urllib.parse.quote(self.model, safe='')}/invoke"
        embeddings = []
        for text in texts:
            response = await asyncio.to_thread(
                rest.post_json,
                url,
                {"inputText": text},
                authenticator=self._authenticator(),
                provider="bedrock",
            )
            embeddings.append(list(response["embedding"]))
        return embeddings

    def get_vector_dimension(self) -> int:
        """Return the dimension of vectors produced by this model.

        Returns:
            The vector dimension size
        """
        return self._profile_dimension(
            "bedrock"
        )  # the dimension is data: ``info["vector_dimension"]`` in profile.toml
