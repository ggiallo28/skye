"""Token counting utilities for different model providers.

This module provides utilities for counting tokens in text and messages
using provider-specific tokenizers. It supports lazy loading of tokenizers
and provides fallback approximation for unknown models.

Example:
    >>> from skye.models.token_counter import TokenCounter
    >>> from skye.base.messages import UserMessage
    >>>
    >>> # Count tokens in text
    >>> count = TokenCounter.count_tokens("Hello, world!", "gpt-4")
    >>> print(count)
    3
    >>>
    >>> # Count tokens in messages
    >>> messages = [UserMessage(content="Hello")]
    >>> count = TokenCounter.count_message_tokens(messages, "gpt-4")
    >>> print(count)
    4
"""

import threading
from typing import Any

from skye.base.exceptions import ValidationError
from skye.base.interfaces.token_counter import TokenCounterInterface
from skye.base.messages import SkyeMessage
from skye.base.plugins import get_registrar
from skye.base.profile import ModelProfile, find_model_profile
from skye.models.lazy_import import LazyImporter

#: Tokens added per message for a model that has no profile. It is the one number this module keeps; every model that a provider
#: profile declares carries its own ``message_overhead`` (Requirement 60.2).
DEFAULT_MESSAGE_OVERHEAD = 3


def tiktoken_tokenizer(model: str) -> Any:
    """The ``"tiktoken"`` tokenizer a ``ModelProfile`` names: the encoding of ``model``, or the estimate when ``tiktoken`` is missing.

    Registered in the registrar as the text ``"skye.models.token_counter:tiktoken_tokenizer"`` by the built-in plugin of
    ``models``. A tokenizer factory takes the model name, because one tokenizer name can serve models with different encodings.
    An unknown model name falls back to ``cl100k_base``; with no ``tiktoken`` installed the estimate is used (no error).
    """
    try:
        tiktoken = LazyImporter.import_module("tiktoken", install_extra="tokens")
        try:
            return tiktoken.encoding_for_model(model)
        except KeyError:
            return tiktoken.get_encoding("cl100k_base")
    except ImportError:
        return TokenCounter._approximate_tokenizer()


class TokenCounter(TokenCounterInterface):
    """Calculate token counts for different models.

    This class provides methods to count tokens in text and messages using
    provider-specific tokenizers. Tokenizers are lazy-loaded only when needed.

    Which tokenizer a model uses and how many tokens each message adds are read from the ``ModelProfile`` of the model (Requirement 59.3),
    found by ``find_model_profile`` in the profiles of the registered providers. A model with no profile is counted with the estimate
    (about 4 characters per token) and ``DEFAULT_MESSAGE_OVERHEAD`` (Requirement 59.10).

    Attributes:
        _tokenizers: Cache of the tokenizer chosen for each model name.
        _registered: The tokenizers set with :meth:`register_tokenizer`, by model name or name prefix (a table of this class, not of the registrar).

    Example:
        >>> count = TokenCounter.count_tokens("Hello", "gpt-4")
        >>> isinstance(count, int)
        True
    """

    # The tokenizer chosen for a model name (lazy loaded)
    _tokenizers: dict[str, Any] = {}
    # The profiles token (``Registrar.profiles_token``) the cache was made under; a write to a profile changes it and empties the cache
    _tokenizers_token: object | None = None
    # The tokenizers that ``register_tokenizer`` sets, by model name or prefix; read without the lock (a copy is published at each write)
    _registered: dict[str, Any] = {}
    _registered_lock = threading.Lock()

    @classmethod
    def register_tokenizer(cls, model: str, tokenizer: Any) -> None:
        """Use ``tokenizer`` to count the tokens of ``model``, for a more exact count than the estimate.

        This is a call of ``TokenCounter`` and not of the plugin interface: the table it writes is the one of this class, and the registrar
        is not touched. A plugin names a tokenizer with ``plugins.tokenizer("name")`` and gives it to the models of a provider through
        ``ModelProfile(tokenizer="name")`` (``plugins.profile(...)`` does it for a model of a provider that exists).

        ``model`` is a model name or the start of one: ``"claude-"`` covers every Claude model, and the longest
        match wins, so ``"claude-3-opus"`` can have its own. A registered tokenizer wins over the one the model's profile names
        and over the estimate. A second call with the same name replaces it. Nothing is installed by this call: the tokenizer is whatever
        the caller already has. Safe to call from several threads.

        Args:
            model: A model name or a name prefix.
            tokenizer: Any object with ``encode(text)`` returning a sized sequence (a ``tiktoken`` encoding, a
                ``tokenizers`` or ``transformers`` tokenizer through a small wrapper, a function of your own).

        Raises:
            ValidationError: ``model`` is empty, or ``tokenizer`` has no callable ``encode``.

        Example:
            >>> class Words:
            ...     def encode(self, text):
            ...         return text.split()
            >>> TokenCounter.register_tokenizer("my-model", Words())
            >>> TokenCounter.count_tokens("one two three", "my-model-v2")
            3
            >>> TokenCounter.unregister_tokenizer("my-model")
            True
        """
        if not isinstance(model, str) or not model:
            raise ValidationError("model must be a non-empty model name or prefix", "model", model)
        if not callable(getattr(tokenizer, "encode", None)):
            raise ValidationError(
                "tokenizer must have an encode(text) method", "tokenizer", tokenizer
            )
        with cls._registered_lock:
            cls._registered = {**cls._registered, model: tokenizer}

    @classmethod
    def unregister_tokenizer(cls, model: str) -> bool:
        """Remove the tokenizer set under exactly ``model`` by ``register_tokenizer``; ``True`` when there was one.

        A tokenizer factory that a provider profile names (``"tiktoken"``) is a registration of the registrar and is not removed by this call.
        """
        with cls._registered_lock:
            if model not in cls._registered:
                return False
            table = dict(cls._registered)
            del table[model]
            cls._registered = table
            return True

    @classmethod
    def _registered_tokenizer(cls, model: str) -> Any | None:
        """The tokenizer set for ``model`` by ``register_tokenizer``: the exact name, else the longest registered prefix."""
        table = cls._registered
        names = [name for name in table if model.startswith(name)]
        return table[max(names, key=len)] if names else None

    @classmethod
    def _model_profile(cls, model: str) -> ModelProfile | None:
        """The ``ModelProfile`` of ``model`` in the profiles of every registered provider, or ``None``.

        An exact name beats a family (a name followed by a date or a version); among families the longest name wins.
        """
        registrar = get_registrar()
        best: tuple[bool, int, ModelProfile] | None = None
        for provider in registrar.names("provider"):
            profile = registrar.get_profile(provider)
            found = find_model_profile(profile, model)
            if found is None or profile is None:
                continue
            name = next(n for n, entry in profile.models.items() if entry is found)
            rank = (name == model, len(name))
            if best is None or rank > best[:2]:
                best = (*rank, found)
        return best[2] if best else None

    @classmethod
    def count_tokens(cls, text: str, model: str) -> int:
        """Count tokens for a given text and model.

        Args:
            text: The text to count tokens for.
            model: The model identifier (e.g., 'gpt-4', 'claude-3-sonnet').

        Returns:
            The number of tokens in the text.

        Example:
            >>> count = TokenCounter.count_tokens("Hello, world!", "gpt-4")
            >>> count > 0
            True
        """
        if not text:
            return 0
        tokenizer = cls._get_tokenizer(model)
        return len(tokenizer.encode(text))

    @classmethod
    def count_message_tokens(cls, messages: list[SkyeMessage], model: str) -> int:
        """Count tokens for a list of messages.

        This method accounts for both the message content and the per-message
        overhead that different models add for formatting.

        Args:
            messages: List of messages to count tokens for.
            model: The model identifier.

        Returns:
            The total number of tokens including message overhead.

        Example:
            >>> from skye.base.messages import UserMessage
            >>> messages = [UserMessage(content="Hello")]
            >>> count = TokenCounter.count_message_tokens(messages, "gpt-4")
            >>> count > 0
            True
        """
        total = 0
        for msg in messages:
            # Add message overhead (varies by model)
            total += cls._get_message_overhead(model)
            total += cls.count_tokens(msg.content or "", model)
        return total

    @classmethod
    def _get_tokenizer(cls, model: str) -> Any:
        """Get tokenizer for model (lazy loaded).

        Args:
            model: The model identifier.

        Returns:
            A tokenizer object with an encode() method.

        Example:
            >>> tokenizer = TokenCounter._get_tokenizer("gpt-4")
            >>> hasattr(tokenizer, 'encode')
            True
        """
        registered = cls._registered_tokenizer(model)
        if registered is not None:
            return registered
        token = get_registrar().profiles_token()
        # A profile was written (``plugins.profile``, a registration): choose the tokenizers again.
        if cls._tokenizers_token is not token:
            cls._tokenizers.clear()
            cls._tokenizers_token = token
        if model not in cls._tokenizers:
            cls._tokenizers[model] = cls._profile_tokenizer(model)
        return cls._tokenizers[model]

    @classmethod
    def _profile_tokenizer(cls, model: str) -> Any:
        """The tokenizer the profile of ``model`` names, or the estimate when it names none or the model has no profile.

        Raises:
            ConfigurationError: The profile names a tokenizer that no plugin has registered.
        """
        profile = cls._model_profile(model)
        if profile is None or profile.tokenizer is None:
            return cls._approximate_tokenizer()
        target = get_registrar().get("tokenizer", profile.tokenizer)
        return target if callable(getattr(target, "encode", None)) else target(model)

    @classmethod
    def _get_message_overhead(cls, model: str) -> int:
        """Get per-message token overhead.

        Different models add different amounts of overhead for message formatting; it is the ``message_overhead`` of the model's profile.

        Args:
            model: The model identifier.

        Returns:
            The number of overhead tokens per message; ``DEFAULT_MESSAGE_OVERHEAD`` for a model with no profile.

        Example:
            >>> overhead = TokenCounter._get_message_overhead("gpt-4")
            >>> overhead >= 0
            True
        """
        profile = cls._model_profile(model)
        return DEFAULT_MESSAGE_OVERHEAD if profile is None else profile.message_overhead

    @staticmethod
    def _approximate_tokenizer() -> Any:
        """Approximate tokenizer for unknown models.

        Uses a simple heuristic: 1 token ≈ 4 characters.

        Returns:
            A tokenizer-like object with an encode() method.

        Example:
            >>> tokenizer = TokenCounter._approximate_tokenizer()
            >>> len(tokenizer.encode("hello"))
            1
        """

        class ApproximateTokenizer:
            """Simple approximate tokenizer based on character count."""

            @staticmethod
            def encode(text: str) -> list[int]:
                """Encode text to approximate token list.

                Args:
                    text: The text to encode.

                Returns:
                    A list of dummy token IDs (length represents token count).
                """
                # Rough approximation: 1 token ≈ 4 characters
                token_count = max(1, len(text) // 4)
                return [0] * token_count

        return ApproximateTokenizer()
