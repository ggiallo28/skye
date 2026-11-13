# D111
# Requirement 56.13, D111
"""Vector encoder interface for embeddings.

This module defines the abstract interface for vector encoding (embeddings)
with support for both synchronous and asynchronous operations.

A plugin author writes ``aencode``, ``aencode_batch`` and ``get_vector_dimension``; ``encode`` and ``encode_batch`` are derived from the async
methods with ``skye.base.sync.run_sync``, so no plugin keeps a second code path. A subclass written for the old base that
defines only ``encode`` and ``encode_batch`` no longer instantiates: it has to write the two async methods.

Raises: ProviderError when the provider call fails, ValidationError for an empty or oversized input.
Missing: an empty list of texts yields an empty list of vectors.
Concurrency: ``encode`` blocks the thread (from a running event loop prefer ``aencode``), ``aencode`` runs on the event loop; an instance is shared by many calls.
"""

from abc import ABC, abstractmethod

from skye.base.sync import run_sync


class VectorEncoderInterface(ABC):
    """Abstract interface for vector encoders.

    This interface defines the contract for embedding implementations that
    convert text into vector representations for semantic search and similarity.
    """

    def encode(self, text: str) -> list[float]:
        """Encode text into a vector: runs ``aencode`` to the end (``run_sync``).

        Args:
            text: The text to encode.

        Returns:
            Vector representation of the text.
        """
        return run_sync(self.aencode(text))

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """Encode multiple texts into vectors: runs ``aencode_batch`` to the end (``run_sync``).

        Args:
            texts: List of texts to encode.

        Returns:
            List of vector representations.
        """
        return run_sync(self.aencode_batch(texts))

    @abstractmethod
    async def aencode(self, text: str) -> list[float]:
        """Encode text into a vector asynchronously.

        Args:
            text: The text to encode.

        Returns:
            Vector representation of the text.
        """
        pass

    @abstractmethod
    async def aencode_batch(self, texts: list[str]) -> list[list[float]]:
        """Encode multiple texts into vectors asynchronously.

        Args:
            texts: List of texts to encode.

        Returns:
            List of vector representations.
        """
        pass

    @abstractmethod
    def get_vector_dimension(self) -> int:
        """Return the dimension of the vectors produced.

        Returns:
            The vector dimension size.
        """
        pass
