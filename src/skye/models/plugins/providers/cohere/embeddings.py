"""Cohere embedding provider implementation.

This module provides the CohereEmbeddingProvider class for generating embeddings
using Cohere's embedding models.

Example:
    >>> from skye.models import CohereEmbeddingProvider
    >>>
    >>> embedder = CohereEmbeddingProvider(
    ...     model="embed-english-v3.0",
    ...     api_key="..."
    ... )
    >>> vector = embedder.encode("Hello, world!")
    >>> vectors = embedder.encode_batch(["text1", "text2"])
"""

import asyncio
from typing import Any

from skye.base.api_keys import api_key_variables
from skye.models.base import BaseEmbeddingProvider
from skye.models.utilities import rest
from skye.models.utilities.credentials import resolve_api_key

_EMBED_PATH = "/v2/embed"  # how to call it; the host is ``default_api_base`` in profile.toml


class CohereEmbeddingProvider(BaseEmbeddingProvider):
    """Cohere embedding provider implementation (stdlib REST, no vendor SDK).

    Supports Cohere's embedding models:
    - embed-english-v3.0 (1024 dimensions)
    - embed-english-light-v3.0 (384 dimensions)
    - embed-multilingual-v3.0 (1024 dimensions)

    Example:
        >>> embedder = CohereEmbeddingProvider(
        ...     model="embed-english-v3.0",
        ...     api_key="..."
        ... )
        >>> vector = embedder.encode("Hello")
        >>> vectors = embedder.encode_batch(["text1", "text2"])
    """

    def __init__(self, model: str, api_key: str | None = None, **config: Any) -> None:
        """Initialize Cohere embedding provider.

        Args:
            model: Model identifier (e.g., 'embed-english-v3.0')
            api_key: Cohere API key; the variable of the profile of ``cohere`` when omitted
            **config: Additional configuration parameters

        Raises:
            ConfigurationError: No key is given and the variable of the profile is not set.
        """
        api_key = resolve_api_key(
            api_key, api_key_variables("cohere")
        )  # the variable of the profile (D18)
        super().__init__(model=model, api_key=api_key, **config)
        self.api_key = api_key

    def _initialize_client(self) -> Any:
        """No vendor SDK is used: requests go through ``skye.models.utilities.rest``.

        Returns:
            None (kept so ``self.client`` remains valid for the base class)
        """
        return None

    async def _aencode_batch_impl(self, texts: list[str]) -> list[list[float]]:
        """Encode multiple texts to vectors using the Cohere v2 REST API (the blocking call runs in
        a worker thread).

        Args:
            texts: List of texts to encode

        Returns:
            List of vector representations
        """
        response = await asyncio.to_thread(
            rest.post_json,
            self._profile_api_base("cohere").rstrip("/") + _EMBED_PATH,
            {
                "model": self.model,
                "texts": texts,
                "input_type": "search_document",
                "embedding_types": ["float"],
            },
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=float(self.config.get("timeout", 60.0)),
            provider="cohere",
        )
        return [list(vector) for vector in response.embeddings.float]

    def get_vector_dimension(self) -> int:
        """Return the dimension of vectors produced by this model.

        Returns:
            The vector dimension size
        """
        return self._profile_dimension(
            "cohere"
        )  # the dimension is data: ``info["vector_dimension"]`` in profile.toml
