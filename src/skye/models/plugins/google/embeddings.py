"""Google (Gemini Enterprise Agent Platform, formerly Vertex AI) embedding provider implementation.

Renamed from `vertex` (Google renamed Vertex AI to Gemini Enterprise Agent Platform in April 2026); the extra is now `google`.

This module provides the GoogleEmbeddingProvider class for generating embeddings
using Google's embedding models.

Example:
    >>> from skye.models import GoogleEmbeddingProvider
    >>>
    >>> embedder = GoogleEmbeddingProvider(
    ...     model="text-embedding-004",
    ...     project_id="my-project",
    ...     location="us-central1"
    ... )
    >>> vector = embedder.encode("Hello, world!")
    >>> vectors = embedder.encode_batch(["text1", "text2"])
"""

from typing import Any

from skye.auth.plugins.google import resolve_google_auth
from skye.base.interfaces.authentication import AuthenticationInterface
from skye.models.base import BaseEmbeddingProvider
from skye.models.plugins.google.provider import _model_url
from skye.models.utilities import rest


class GoogleEmbeddingProvider(BaseEmbeddingProvider):
    """Google embedding provider implementation.

    Supports Google's embedding models:
    - text-embedding-004 (768 dimensions)
    - text-multilingual-embedding-002 (768 dimensions)

    Example:
        >>> embedder = GoogleEmbeddingProvider(
        ...     model="text-embedding-004",
        ...     project_id="my-project",
        ...     location="us-central1"
        ... )
        >>> vector = embedder.encode("Hello")
        >>> vectors = embedder.encode_batch(["text1", "text2"])
    """

    MAX_INSTANCES = 250  # per :predict request

    def __init__(self, model: str, project_id: str, location: str, **config: Any) -> None:
        """Initialize Google embedding provider.

        Args:
            model: Model identifier (e.g., 'text-embedding-004')
            project_id: Google Cloud project ID
            location: Region location (e.g., 'us-central1')
            **config: Additional configuration parameters
        """
        super().__init__(model=model, project_id=project_id, location=location, **config)
        self.project_id = project_id
        self.location = location
        self.credentials = config.get("credentials")
        self._authenticator: AuthenticationInterface | None = None

    def _initialize_client(self) -> Any:
        """No vendor SDK: requests go through the stdlib REST transport."""
        return None

    @property
    def authenticator(self) -> AuthenticationInterface:
        if self._authenticator is None:
            self._authenticator = resolve_google_auth(self.credentials)
        return self._authenticator

    def _encode_batch_impl(self, texts: list[str]) -> list[list[float]]:
        """Encode multiple texts to vectors using Google API.

        Args:
            texts: List of texts to encode

        Returns:
            List of vector representations
        """
        url = _model_url(self.location, self.project_id, self.model, "predict")
        vectors: list[list[float]] = []
        for i in range(0, len(texts), self.MAX_INSTANCES):
            batch = texts[i : i + self.MAX_INSTANCES]
            body = {"instances": [{"content": t} for t in batch]}
            response = rest.post_json(
                url, body, authenticator=self.authenticator, provider="google"
            )
            vectors.extend(
                list(p["embeddings"]["values"]) for p in response.to_dict().get("predictions", [])
            )
        return vectors

    def get_vector_dimension(self) -> int:
        """Return the dimension of vectors produced by this model.

        Returns:
            The vector dimension size
        """
        return self._profile_dimension(
            "google"
        )  # the dimension is data: ``info["vector_dimension"]`` in profile.toml
