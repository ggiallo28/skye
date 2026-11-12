"""OpenAI embedding provider implementation.

This module provides the OpenAIEmbeddingProvider class for generating embeddings
using OpenAI's embedding models.

Example:
    >>> from skye.models import OpenAIEmbeddingProvider
    >>>
    >>> embedder = OpenAIEmbeddingProvider(
    ...     model="text-embedding-3-small",
    ...     api_key="sk-..."
    ... )
    >>> vector = embedder.encode("Hello, world!")
    >>> vectors = embedder.encode_batch(["text1", "text2"])
"""

import asyncio
from typing import Any

from skye.models.base import BaseEmbeddingProvider
from skye.models.utilities import rest
from skye.base.api_keys import api_key_variables
from skye.models.utilities.credentials import resolve_api_key


class OpenAIEmbeddingProvider(BaseEmbeddingProvider):
    """OpenAI embedding provider implementation.

    Supports OpenAI's embedding models:
    - text-embedding-3-small (1536 dimensions)
    - text-embedding-3-large (3072 dimensions)
    - text-embedding-ada-002 (1536 dimensions)

    Example:
        >>> embedder = OpenAIEmbeddingProvider(
        ...     model="text-embedding-3-small",
        ...     api_key="sk-..."
        ... )
        >>> vector = embedder.encode("Hello")
        >>> vectors = embedder.encode_batch(["text1", "text2"])
    """

    def __init__(self, model: str, api_key: str | None = None, **config: Any) -> None:
        """Initialize OpenAI embedding provider.

        Args:
            model: Model identifier (e.g., 'text-embedding-3-small')
            api_key: OpenAI API key; the variable of the profile of ``openai`` when omitted
            **config: Additional configuration parameters

        Raises:
            ConfigurationError: No key is given and the variable of the profile is not set.
        """
        api_key = resolve_api_key(api_key, api_key_variables("openai"))  # the variable of the profile (D18)
        super().__init__(model=model, api_key=api_key, **config)
        self.api_key = api_key

    def _initialize_client(self) -> Any:
        """No vendor client: requests go through the standard-library REST transport."""
        return None

    def _encode_batch_impl(self, texts: list[str]) -> list[list[float]]:
        """Encode multiple texts to vectors using the OpenAI embeddings endpoint."""
        base = (self.config.get("api_base") or self._profile_api_base("openai")).rstrip("/")
        response = rest.post_json(
            f"{base}/embeddings",
            {"model": self.model, "input": texts},
            headers={"Authorization": f"Bearer {self.api_key}"},
            provider="openai",
        )
        return [item.embedding for item in response.data]

    async def _aencode_batch_impl(self, texts: list[str]) -> list[list[float]]:
        """Encode asynchronously (sync REST call run in the default executor)."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._encode_batch_impl, texts)

    def get_vector_dimension(self) -> int:
        """Return the dimension of vectors produced by this model.

        Returns:
            The vector dimension size
        """
        return self._profile_dimension(
            "openai"
        )  # the dimension is data: ``info["vector_dimension"]`` in profile.toml
