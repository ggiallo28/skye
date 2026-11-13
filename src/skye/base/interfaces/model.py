"""Model interface for LLM providers.

This module defines the abstract interface that all LLM provider implementations
must follow. It supports both synchronous and asynchronous operations, streaming,
and provides a unified API regardless of the underlying provider.

**Polymorphic Input Support:**
The ModelInterface works with CompleteRequest which accepts either:
- **messages**: List of SkyeMessage objects (base Skye)
- **prompt**: Template name with variables (requires skyeai[prompts])

Implementations should handle both cases transparently. If a prompt is provided,
the implementation should resolve it to messages before calling the LLM.

Example (Base Skye):
    >>> from skye.base.interfaces.model import ModelInterface
    >>> from skye.base.completion import CompleteRequest
    >>> from skye.base.messages import UserMessage
    >>>
    >>> # Using messages directly
    >>> request = CompleteRequest(
    ...     messages=[UserMessage(content="Hello")],
    ...     model="gpt-4"
    ... )
    >>> response = model.complete(request)  # doctest: +SKIP

Example (With skyeai[prompts]):
    >>> # Using prompt templates
    >>> request = CompleteRequest(
    ...     prompt="greeting",
    ...     prompt_variables={"name": "Alice"},
    ...     model="gpt-4"
    ... )
    >>> response = model.complete(request)  # doctest: +SKIP

Raises: ProviderError when the provider call fails, ValidationError when the request is invalid, ConfigurationError for a missing credential or model.
Missing: not applicable; a response or an exception, never ``None``.
Concurrency: ``complete`` and ``stream`` block the calling thread, ``acomplete`` and ``astream`` run on the event loop; an instance is shared by many calls and must not keep per-request state.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Iterator
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from skye.base.completion import CompleteRequest, CompleteResponse, StreamChunk



# decision D36
class ModelInterface(ABC):
    """Abstract interface for LLM providers.

    This interface defines the contract that all LLM provider implementations
    must follow. It provides methods for synchronous and asynchronous completion,
    streaming, and model metadata retrieval.

    All methods are abstract and must be implemented by concrete provider classes.

    **The call:** ``complete``, ``stream``, ``acomplete`` and ``astream`` take what users write,
    ``client.complete(messages=[...], model="gpt-4")``, and also one ``CompleteRequest`` as the first argument,
    ``client.complete(request)``.

    **Polymorphic Input Handling:**
    Implementations should handle CompleteRequest with either:
    - `request.messages` - Direct message list (base Skye)
    - `request.prompt` - Template name to resolve (requires skyeai[prompts])

    When `request.prompt` is provided, implementations should:
    1. Check if a PromptBuilder is available (skyeai[prompts] installed)
    2. Resolve the prompt template to messages
    3. Proceed with the completion using the resolved messages

    This allows the same interface to work seamlessly with or without
    the optional prompts package.

    Example:
        >>> class OpenAIModel(ModelInterface):
        ...     def complete(self, messages=None, model=None, router=None, temperature=None, max_tokens=None, **kwargs):
        ...         request = messages if isinstance(messages, CompleteRequest) else CompleteRequest(messages=messages, model=model, **kwargs)
        ...         # Handle polymorphic input
        ...         if request.prompt:
        ...             # Resolve prompt to messages (if skyeai[prompts] available)
        ...             messages = self._resolve_prompt(request.prompt, request.prompt_variables)
        ...         else:
        ...             messages = request.messages...
        ...         # Call OpenAI API with messages
        ...         return self._call_api(messages, request)...
        ...     def stream(self, messages=None, model=None, router=None, temperature=None, max_tokens=None, **kwargs):
        ...         # Stream from OpenAI API
        ...         pass...
        ...     async def acomplete(self, messages=None, model=None, router=None, temperature=None, max_tokens=None, **kwargs):
        ...         # Async call to OpenAI API
        ...         pass...
        ...     async def astream(self, messages=None, model=None, router=None, temperature=None, max_tokens=None, **kwargs):
        ...         # Async stream from OpenAI API
        ...         yield StreamChunk(delta="")...
        ...     def get_model_info(self) -> dict:
        ...         return {"name": "gpt-4", "provider": "openai"}
    """

    @abstractmethod
    def complete(
        self,
        messages: list[Any] | str | CompleteRequest | None = None,
        model: str | None = None,
        router: Any | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> CompleteResponse:
        """Execute a synchronous completion request.

        Accepts polymorphic input via CompleteRequest:
        - Use `request.messages` for direct message input (base Skye)
        - Use `request.prompt` + `request.prompt_variables` for template-based input
          (skyeai[prompts])

        Args:
            messages: A list of messages, a string (one user message) or one ``CompleteRequest`` as the first argument.
            model: Model identifier (not together with ``router``).
            router: A router that selects the model (not together with ``model``).
            temperature: Sampling temperature; the request default when omitted.
            max_tokens: Maximum tokens to generate; the request default when omitted.
            **kwargs: Other fields of ``CompleteRequest`` (``capabilities``, ``response_schema``, ...).

        Returns:
            CompleteResponse containing the model's response and metadata.

        Raises:
            ProviderError: If the provider API call fails.
            ValidationError: If the request is invalid.

        Example (Base Skye):
            >>> request = CompleteRequest(
            ...     messages=[UserMessage(content="Hello")],
            ...     model="gpt-4"
            ... )
            >>> response = model.complete(request)
            >>> print(response.content)

        Example (With skyeai[prompts]):
            >>> request = CompleteRequest(
            ...     prompt="greeting",
            ...     prompt_variables={"name": "Alice"},
            ...     model="gpt-4"
            ... )
            >>> response = model.complete(request)
            >>> print(response.content)
        """
        pass

    @abstractmethod
    def stream(
        self,
        messages: list[Any] | str | CompleteRequest | None = None,
        model: str | None = None,
        router: Any | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> Iterator[StreamChunk]:
        """Execute a streaming completion request.

        Args:
            messages: A list of messages, a string (one user message) or one ``CompleteRequest`` as the first argument.
            model: Model identifier (not together with ``router``).
            router: A router that selects the model (not together with ``model``).
            temperature: Sampling temperature; the request default when omitted.
            max_tokens: Maximum tokens to generate; the request default when omitted.
            **kwargs: Other fields of ``CompleteRequest``.

        Yields:
            StreamChunk objects containing incremental response data.

        Raises:
            ProviderError: If the provider API call fails.
            ValidationError: If the request is invalid.

        Example:
            >>> request = CompleteRequest(
            ...     messages=[UserMessage(content="Hello")],
            ...     model="gpt-4",
            ...     stream=True
            ... )
            >>> for chunk in model.stream(request):
            ...     print(chunk.delta, end="")
        """
        pass

    @abstractmethod
    async def acomplete(
        self,
        messages: list[Any] | str | CompleteRequest | None = None,
        model: str | None = None,
        router: Any | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> CompleteResponse:
        """Execute an asynchronous completion request.

        Args:
            messages: A list of messages, a string (one user message) or one ``CompleteRequest`` as the first argument.
            model: Model identifier (not together with ``router``).
            router: A router that selects the model (not together with ``model``).
            temperature: Sampling temperature; the request default when omitted.
            max_tokens: Maximum tokens to generate; the request default when omitted.
            **kwargs: Other fields of ``CompleteRequest``.

        Returns:
            CompleteResponse containing the model's response and metadata.

        Raises:
            ProviderError: If the provider API call fails.
            ValidationError: If the request is invalid.

        Example:
            >>> request = CompleteRequest(
            ...     messages=[UserMessage(content="Hello")],
            ...     model="gpt-4"
            ... )
            >>> response = await model.acomplete(request)
            >>> print(response.content)
        """
        pass

    @abstractmethod
    async def astream(
        self,
        messages: list[Any] | str | CompleteRequest | None = None,
        model: str | None = None,
        router: Any | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """Execute an asynchronous streaming completion request (an async generator: iterate it with ``async for``, do not await it).

        Args:
            messages: A list of messages, a string (one user message) or one ``CompleteRequest`` as the first argument.
            model: Model identifier (not together with ``router``).
            router: A router that selects the model (not together with ``model``).
            temperature: Sampling temperature; the request default when omitted.
            max_tokens: Maximum tokens to generate; the request default when omitted.
            **kwargs: Other fields of ``CompleteRequest``.

        Yields:
            StreamChunk objects containing incremental response data.

        Raises:
            ProviderError: If the provider API call fails.
            ValidationError: If the request is invalid.

        Example:
            >>> request = CompleteRequest(
            ...     messages=[UserMessage(content="Hello")],
            ...     model="gpt-4",
            ...     stream=True
            ... )
            >>> async for chunk in model.astream(request):
            ...     print(chunk.delta, end="")
        """
        raise NotImplementedError
        yield  # pragma: no cover  (makes this an async generator)

    @abstractmethod
    def get_model_info(self) -> dict[str, Any]:
        """Return metadata about the model.

        Returns:
            Dictionary containing model metadata such as name, provider,
            capabilities, and other relevant information.

        Example:
            >>> info = model.get_model_info()
            >>> print(info["provider"])
            'openai'
            >>> print(info["name"])
            'gpt-4'
        """
        pass
