"""Google (Gemini Enterprise Agent Platform, formerly Vertex AI) multimodal embedding provider.

Renamed from `vertex` (Google renamed Vertex AI to Gemini Enterprise Agent Platform in April 2026); the extra is now `google`.

This module provides the GoogleMultimodalEmbeddingProvider class for generating
embeddings from text and images using Google's multimodal embedding model.

Example:
    >>> from skye.models import GoogleMultimodalEmbeddingProvider
    >>>
    >>> embedder = GoogleMultimodalEmbeddingProvider(
    ...     project_id="my-project",
    ...     location="us-central1"
    ... )
    >>> # Text embedding
    >>> vector = embedder.encode("Hello, world!")
    >>> # Image embedding
    >>> vector = embedder.encode("path/to/image.jpg")
    >>> # Batch with mixed content
    >>> vectors = embedder.encode_batch(["text1", "path/to/image.jpg"])
"""

import base64
from typing import Any

from skye.auth.plugins.google import resolve_google_auth
from skye.base import http
from skye.base.interfaces.authentication import AuthenticationInterface
from skye.models.base import BaseEmbeddingProvider
from skye.models.plugins.google.provider import _model_url
from skye.models.utilities import rest
from skye.models.utilities.multimodal import ImageHandler


class GoogleMultimodalEmbeddingProvider(BaseEmbeddingProvider):
    """Google multimodal embedding provider implementation.

    Supports Google's multimodal embedding model:
    - multimodalembedding@001 (1408 dimensions)

    This provider can encode both text and images into the same vector space,
    enabling cross-modal retrieval and similarity search.

    Example:
        >>> embedder = GoogleMultimodalEmbeddingProvider(
        ...     project_id="my-project",
        ...     location="us-central1"
        ... )
        >>> # Text embedding
        >>> text_vector = embedder.encode("Hello")
        >>> # Image embedding
        >>> image_vector = embedder.encode("path/to/image.jpg")
        >>> # Batch encoding
        >>> vectors = embedder.encode_batch(["text1", "image.jpg"])
    """

    # Model dimensions
    MODEL_NAME = "multimodalembedding@001"

    def __init__(
        self, project_id: str, location: str, model: str | None = None, **config: Any
    ) -> None:
        """Initialize Google multimodal embedding provider.

        Args:
            project_id: Google Cloud project ID
            location: Region location (e.g., 'us-central1')
            model: The model (default ``multimodalembedding@001``)
            **config: Additional configuration parameters
        """
        super().__init__(
            model=model or self.MODEL_NAME, project_id=project_id, location=location, **config
        )
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

    def _predict(self, instance: dict[str, Any]) -> dict[str, Any]:
        url = _model_url(self.location, self.project_id, self.model, "predict")
        response = rest.post_json(
            url, {"instances": [instance]}, authenticator=self.authenticator, provider="google"
        )
        predictions = response.to_dict().get("predictions") or [{}]
        first: dict[str, Any] = predictions[0]
        return first

    def _encode_batch_impl(self, texts: list[str]) -> list[list[float]]:
        """Encode multiple texts/images to vectors.

        Each item in texts can be:
        - Plain text string
        - File path to an image
        - URL to an image
        - Base64-encoded image data

        Args:
            texts: List of texts or image paths to encode

        Returns:
            List of vector representations
        """
        embeddings = []

        for item in texts:
            # Try to detect if it's an image
            if self._is_image_input(item):
                # Process as image
                embedding = self._encode_image(item)
            else:
                # Process as text
                embedding = self._encode_text(item)

            embeddings.append(embedding)

        return embeddings

    def _is_image_input(self, item: str) -> bool:
        """Detect if input is an image.

        Args:
            item: Input string to check

        Returns:
            True if input appears to be an image, False otherwise
        """
        # Check for image file extensions
        image_extensions = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
        item_lower = item.lower()

        # Check file extension
        for ext in image_extensions:
            if item_lower.endswith(ext):
                return True

        # Check for URLs
        if item.startswith("http://") or item.startswith("https://"):
            # Could be image URL, check common patterns
            if any(ext in item_lower for ext in image_extensions):
                return True

        # Check for base64 image data
        if item.startswith("data:image/"):
            return True

        return False

    def _encode_text(self, text: str) -> list[float]:
        """Encode text to vector via ``:predict`` (``textEmbedding``)."""
        return list(self._predict({"text": text})["textEmbedding"])

    def _encode_image(self, image_input: str) -> list[float]:
        """Encode an image (path, URL, data URL or ``gs://`` URI) to a vector.

        Local files and data URLs are sent as ``bytesBase64Encoded``; ``gs://`` URIs as ``gcsUri``;
        ``http(s)`` URLs are downloaded and sent as bytes.
        """
        if image_input.startswith("gs://"):
            image: dict[str, Any] = {"gcsUri": image_input}
        else:
            processed = ImageHandler.process_image(image_input)
            url = processed["image_url"]["url"] if processed["type"] == "image_url" else image_input
            if url.startswith("data:"):
                image = {"bytesBase64Encoded": url.split(",", 1)[1]}
            else:
                raw = http.send_bytes(url, None, method="GET", provider="google")
                image = {"bytesBase64Encoded": base64.b64encode(raw).decode("ascii")}
        return list(self._predict({"image": image})["imageEmbedding"])

    def get_vector_dimension(self) -> int:
        """Return the dimension of vectors produced by this model.

        Returns:
            The vector dimension size (1408 for multimodalembedding@001)
        """
        return self._profile_dimension("google-multimodal")
