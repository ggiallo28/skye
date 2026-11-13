"""Base provider classes for model and embedding providers.

This module provides abstract base classes that all provider implementations
must inherit from. These classes handle common functionality like lazy client
initialization, error handling, request/response transformation, and retry logic.

## Provider Transformation Architecture

All provider-specific transformation logic MUST be encapsulated within provider
client classes. This ensures the core library remains completely provider-agnostic
and makes it easy to add new providers without modifying core code.

### Transformation Responsibilities

Each provider client handles ALL transformations for that provider:
- Message format conversion (Skye messages → provider format)
- Capability format conversion (Skye capabilities → provider capabilities)
- Capability call extraction (provider response → Skye CapabilityCall objects)
- Parameter mapping and provider-specific options

### Core Library Provider Agnosticism

Core library modules MUST NOT contain provider-specific code:
- src/skye/router/ - Router and routing logic
- src/skye/tools/ - Capability system
- src/skye/base/completion.py - Completion models
- src/skye/base/messages.py - Message models

### Adding a New Provider

To add a new provider, you only need to:
1. Create a new provider class inheriting from BaseModelProvider
2. Implement all required transformation methods
3. No changes to core library code required

See docs/guides/extend/custom-provider.md for how provider adapters are built.
"""

import dataclasses
import inspect
import logging
import time
from abc import ABC, abstractmethod
from contextlib import aclosing
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Iterator
from typing import Any

from skye.base.completion import CompleteRequest, CompleteResponse, StreamChunk, TokenUsage
from skye.base.exceptions import ProviderError, ProviderTimeoutError, ValidationError
from skye.base.health import HealthMetrics
from skye.base.http import _is_timeout
from skye.base.interfaces.model import ModelInterface
from skye.base.interfaces.vector_encoder import VectorEncoderInterface
from skye.base.log_event import (
    ModelInvocationEvent,
    model_invocation_end,
    model_invocation_error,
    model_invocation_start,
    model_invocation_summary,
    new_correlation_id,
)
from skye.base.prompt_parts import PromptParts
from skye.base.sync import iterate_sync, run_sync
from skye.models.utilities.capability_choice import acomplete_emulated, emulated_request, forced_choice
from skye.models.cost import CostCalculator, check_pricing
from skye.models.utilities.prompt_parts import request_from_parts
from skye.models.utilities.retry import (
    DEFAULT_MAX_RETRIES,
    acall_with_retry,
    is_retryable,
    retry_wait,
    sleep_for,
)
from skye.models.utilities.structured import parse_structured
from skye.models.token_counter import TokenCounter

logger = logging.getLogger(__name__)


class _SchemaCapability:
    """A capability known only by its schema (from a ``ToolProvider``): enough to offer it to a model."""

    __slots__ = ("_schema",)

    def __init__(self, schema: Any) -> None:
        self._schema = schema

    def get_schema(self) -> Any:
        return self._schema

    def __repr__(self) -> str:
        return f"_SchemaCapability({getattr(self._schema, 'name', '?')!r})"


def capability_list(source: Any) -> list[Any]:
    """The capabilities to offer the model, from what ``CompleteRequest.capabilities`` holds.

    A list (or tuple) of capabilities or tool dicts is kept; a ``CapabilityRegistry`` or any ``ToolProvider`` (anything with
    ``list_schemas``) gives its schemas.

    Raises:
        ValidationError: ``source`` is none of these.
    """
    if isinstance(source, (list, tuple)):
        return list(source)
    if hasattr(source, "list_schemas"):
        schemas = run_sync(source.list_schemas())
        return [_SchemaCapability(schema) for schema in schemas]
    raise ValidationError(
        "capabilities must be a list of capabilities, a CapabilityRegistry or a ToolProvider",
        field="capabilities",
        value=type(source).__name__,
    )


# decision D104, Requirement 9.2, Requirement 19
class BaseModelProvider(ModelInterface, ABC):
    """Abstract base class for model providers.
    
    This class provides common functionality for all LLM provider implementations,
    including lazy client initialization, error handling, and a template method
    pattern for request/response transformation.
    
    **Provider-Specific Transformation Encapsulation:**
    
    All provider-specific transformation logic MUST be contained within the
    provider client class. This ensures the core library remains provider-agnostic
    and makes it easy to add new providers without modifying core code.
    
    Each provider client handles ALL transformations for that provider:
    - Message format conversion (Skye messages → provider format)
    - Capability format conversion (Skye capabilities → provider capabilities)
    - Capability call extraction (provider response → Skye CapabilityCall objects)
    - Parameter mapping and provider-specific options
    
    Subclasses must implement:
    - _initialize_client(): Create the provider-specific client
    - _transform_request(): Convert CompleteRequest to provider format
    - _transform_response(): Convert provider response to CompleteResponse
    - _transform_stream_chunk(): Convert provider stream chunk to StreamChunk
    - _transform_messages(): Convert Skye messages to provider format
    - _transform_capabilities(): Convert Skye capabilities to provider format
    - _extract_capability_calls(): Extract capability calls from provider response
    - _acall_provider(): Make the actual provider API call (async; ``complete`` and ``stream`` are derived from the async methods)
    - _acall_provider_stream(): Make streaming provider API call (an async generator)
    - get_model_info(): Return model metadata
    
    Example:
        >>> class OpenAIProvider(BaseModelProvider):
        ...     def _initialize_client(self):
        ...         import openai
        ...         return openai.OpenAI(api_key=self.config["api_key"])...
        ...     def _transform_request(self, request):
        ...         # Use internal transformation methods
        ...         return {
        ...             "model": request.model,
        ...             "messages": self._transform_messages(request.messages),
        ...             "tools": self._transform_capabilities(request.capabilities)
        ...         }...
        ...     def _transform_messages(self, messages):
        ...         # OpenAI-specific message transformation
        ...         return [{"role": m.role, "content": m.content} for m in messages]...
        ...     def _transform_capabilities(self, capabilities):
        ...         # OpenAI-specific capability transformation
        ...         return [{"type": "function", "function": {...}} for c in capabilities]...
        ...     def _extract_capability_calls(self, response):
        ...         # Extract capability calls from OpenAI response
        ...         return [CapabilityCall(...) for tc in response.capability_calls]...
        ...     # ... implement other abstract methods

    Retries: a client retries a ``RateLimitError``, a ``ServerError`` or a ``ProviderTimeoutError`` up to
    ``max_retries`` times (3 by default), waiting with exponential backoff or the server's ``Retry-After``; any other error
    is raised at once. A stream is retried only before its first chunk. ``max_retries=0`` turns retries off (the router
    does this for its targets, so its own policy decides).

    Cost: every response carries ``metadata["cost"]`` (``prompt``, ``completion``, ``total``, ``currency``,
    ``exact``), priced with the provider's own token count; the tokens are estimated, with ``exact`` false, only when the
    provider reports none. A model with no price has ``cost`` ``None``. ``pricing={"prompt": p, "completion": c}`` (USD per 1M
    tokens) prices this client's calls with your own numbers. A stream carries the running tokens and cost on its chunks.
    """

    #: The first backoff wait in seconds; it doubles with each retry.
    retry_base_wait: float = 1.0
    #: The longest backoff wait in seconds (a ``Retry-After`` may ask for more, up to 60).
    retry_max_wait: float = 20.0

    def __init__(self, model: str | None = None, router: Any | None = None, **config: Any) -> None:
        """Initialize base provider with configuration.
        
        Args:
            model: Model identifier (optional, can be provided in request)
            router: Model router for load balancing (optional)
            **config: Provider-specific configuration parameters. Three are read here and not kept in ``config``:
                ``max_retries`` (retries of a transient failure, default 3; ``0`` turns them off), ``retry_sleep``
                (the function that waits between attempts, ``asyncio.sleep`` by default; tests pass one that records, and if it returns an awaitable that is awaited) and
                ``pricing`` (``{"prompt": p, "completion": c}`` in USD per 1M tokens, for the cost of this client's calls).
        """
        if model is not None and router is not None:
            raise ValueError("Cannot provide both 'model' and 'router'")
        max_retries = config.pop("max_retries", DEFAULT_MAX_RETRIES)
        if not isinstance(max_retries, int) or isinstance(max_retries, bool) or max_retries < 0:
            raise ValueError(f"max_retries must be an integer >= 0, got {max_retries!r}")
        self.max_retries: int = max_retries
        self.retry_sleep: Callable[[float], Any] | None = config.pop("retry_sleep", None)
        self.pricing: dict[str, float] | None = check_pricing(config.pop("pricing", None))

        self.model = model
        self.router = router
        self.config = config
        self._client = None
        self.health_metrics = HealthMetrics()
    
    @property
    def default_model(self) -> str | None:
        """Get the default model for this provider.
        
        Returns:
            The default model identifier, or None if not set
        """
        return self.model
    
    @property
    def client(self) -> Any:
        """Lazy-load the provider client.
        
        The client is only initialized when first accessed, reducing startup
        time and memory usage.
        
        Returns:
            The provider-specific client instance
        """
        if self._client is None:
            self._client = self._initialize_client()
        return self._client
    
    @abstractmethod
    def _initialize_client(self) -> Any:
        """Initialize the provider-specific client.
        
        This method should create and return the provider's SDK client.
        It will be called lazily when the client is first accessed.
        
        Returns:
            The initialized provider client
            
        Example:
            >>> def _initialize_client(self):
            ...     import openai
            ...     return openai.OpenAI(api_key=self.config["api_key"])
        """
        pass
    
    @abstractmethod
    def _transform_request(self, request: CompleteRequest) -> dict[str, Any]:
        """Transform CompleteRequest to provider-specific format.
        
        Args:
            request: The skye CompleteRequest
            
        Returns:
            Dictionary in provider-specific format
            
        Example:
            >>> def _transform_request(self, request):
            ...     return {
            ...         "model": request.model,
            ...         "messages": [{"role": "user", "content": "..."}],
            ...         "temperature": request.temperature
            ...     }
        """
        pass
    
    @abstractmethod
    def _transform_response(self, response: Any) -> CompleteResponse:
        """Transform provider response to CompleteResponse.
        
        Args:
            response: The provider-specific response object
            
        Returns:
            CompleteResponse in skye format
            
        Example:
            >>> def _transform_response(self, response):
            ...     return CompleteResponse(
            ...         id=response.id,
            ...         model=response.model,
            ...         provider="openai",
            ...         content=response.choices[0].message.content,
            ...         finish_reason=response.choices[0].finish_reason,
            ...         usage=TokenUsage(...)
            ...     )
        """
        pass
    
    @abstractmethod
    def _transform_stream_chunk(self, chunk: Any) -> StreamChunk:
        """Transform provider stream chunk to StreamChunk.
        
        Args:
            chunk: The provider-specific stream chunk
            
        Returns:
            StreamChunk in skye format
            
        Example:
            >>> def _transform_stream_chunk(self, chunk):
            ...     return StreamChunk(
            ...         id=chunk.id,
            ...         delta=chunk.choices[0].delta.content or "",
            ...         finish_reason=chunk.choices[0].finish_reason,
            ...         index=chunk.choices[0].index
            ...     )
        """
        pass
    
    # Requirement 56.13
    @abstractmethod
    async def _acall_provider(self, request: dict[str, Any]) -> Any:
        """Make the actual provider API call (async: a plugin writes this one only).

        Args:
            request: Provider-specific request dictionary

        Returns:
            Provider-specific response object

        Example:
            >>> async def _acall_provider(self, request):
            ...     return await self.client.chat.completions.create(**request)
        """
        pass

    @abstractmethod
    def _acall_provider_stream(self, request: dict[str, Any]) -> AsyncGenerator[Any, None]:
        """Make streaming provider API call (an async generator: ``async def`` with ``yield``).

        Args:
            request: Provider-specific request dictionary

        Yields:
            Provider-specific stream chunks

        Example:
            >>> async def _acall_provider_stream(self, request):
            ...     async for chunk in await self.client.chat.completions.create(**request):
            ...         yield chunk
        """
        pass

    @abstractmethod
    def _transform_messages(self, messages: list[Any]) -> Any:
        """Transform Skye messages to provider-specific format.

        The shape is the provider's: most return the list of wire messages, Anthropic returns the system text and the list.
        
        This method encapsulates all provider-specific message transformation logic.
        Each provider has different requirements for message format, and this method
        handles those differences.
        
        **Provider-Specific Responsibilities:**
        - Convert Skye message objects to provider's message format
        - Handle system messages (some providers require separate handling)
        - Handle capability messages and results
        - Handle multimodal content (images, etc.)
        - Map message roles to provider-specific roles
        
        Args:
            messages: List of Skye message objects (UserMessage, AssistantMessage, etc.)
            
        Returns:
            List of dictionaries in provider-specific message format
            
        Example (OpenAI):
            >>> def _transform_messages(self, messages):
            ...     return [
            ...         {"role": msg.role, "content": msg.content}
            ...         for msg in messages
            ...     ]
        
        Example (Bedrock):
            >>> def _transform_messages(self, messages):
            ...     return [
            ...         {"role": msg.role, "content": [{"text": msg.content}]}
            ...         for msg in messages
            ...     ]
        """
        pass
    
    @abstractmethod
    def _transform_capabilities(self, capabilities: list[Any]) -> list[dict[str, Any]]:
        """Transform Skye capabilities to provider-specific capability format.
        
        This method encapsulates all provider-specific capability transformation
        logic. Each provider has different requirements for capability definitions, and this
        method handles those differences.
        
        **Provider-Specific Responsibilities:**
        - Convert CapabilityInterface objects to provider's capability format
        - Generate proper JSON Schema for capability parameters
        - Handle provider-specific capability metadata
        - Map capability names and descriptions appropriately
        
        Args:
            capabilities: List of CapabilityInterface objects
            
        Returns:
            List of dictionaries in provider-specific capability format
            
        Example (OpenAI):
            >>> def _transform_capabilities(self, capabilities):
            ...     return [
            ...         {
            ...             "type": "function",
            ...             "function": {
            ...                 "name": cap.get_schema().name,
            ...                 "description": cap.get_schema().description,
            ...                 "parameters": cap.get_schema().parameters
            ...             }
            ...         }
            ...         for cap in capabilities
            ...     ]
        
        Example (Bedrock):
            >>> def _transform_capabilities(self, capabilities):
            ...     return [
            ...         {
            ...             "toolSpec": {
            ...                 "name": cap.get_schema().name,
            ...                 "description": cap.get_schema().description,
            ...                 "inputSchema": {"json": cap.get_schema().parameters}
            ...             }
            ...         }
            ...         for cap in capabilities
            ...     ]
        """
        pass
    
    @abstractmethod
    def _extract_capability_calls(self, response: Any) -> list[Any] | None:
        """Extract capability calls from provider response.
        
        This method encapsulates provider-specific logic for extracting capability
        calls from the provider's response and converting them to Skye CapabilityCall
        objects.
        
        **Provider-Specific Responsibilities:**
        - Parse capability calls from provider response format
        - Extract capability call ID, name, and arguments
        - Convert to CapabilityCall objects
        - Handle JSON parsing of arguments if needed
        - Return None if no capability calls present
        
        Args:
            response: Provider-specific response object
            
        Returns:
            List of CapabilityCall objects, or None if no capability calls
            
        Example (OpenAI):
            >>> def _extract_capability_calls(self, response):
            ...     if not hasattr(response.choices[0].message, "capability_calls"):
            ...         return None
            ...     
            ...     from skye.tools.capability_models import CapabilityCall
            ...     import json
            ...     
            ...     capability_calls = []
            ...     for tc in response.choices[0].message.capability_calls:
            ...         capability_calls.append(
            ...             CapabilityCall(
            ...                 id=tc.id,
            ...                 name=tc.function.name,
            ...                 arguments=json.loads(tc.function.arguments)
            ...             )
            ...         )
            ...     return capability_calls
        
        Example (Bedrock):
            >>> def _extract_capability_calls(self, response):
            ...     capability_calls = []
            ...     for block in response["output"]["message"].get("content", []):
            ...         if "toolUse" in block:
            ...             tool_use = block["toolUse"]
            ...             capability_calls.append(
            ...                 CapabilityCall(
            ...                     id=tool_use["toolUseId"],
            ...                     name=tool_use["name"],
            ...                     arguments=tool_use["input"]
            ...                 )
            ...             )
            ...     return capability_calls if capability_calls else None
        """
        pass

    def parse_capability_calls(self, response: Any) -> list[Any]:
        """Parse capability calls from provider response using provider-specific logic.
        
        This is a public interface that delegates to the provider-specific
        _extract_capability_calls method. It provides a consistent interface
        for the CapabilityCallHandler to use.
        
        Args:
            response: Provider-specific response object (CompleteResponse or raw response)
            
        Returns:
            List of CapabilityCall objects (empty list if none found)
            
        Example:
            >>> provider = OpenAIProvider(api_key="...")
            >>> response = provider.complete(request)
            >>> capability_calls = provider.parse_capability_calls(response)
        """
        # If it's a CompleteResponse and already has capability_calls, return them
        if hasattr(response, 'capability_calls') and response.capability_calls is not None:
            calls: list[Any] = response.capability_calls
            return calls
        
        # Handle both CompleteResponse and raw provider response
        if hasattr(response, 'metadata') and 'raw_response' in response.metadata:
            # Use raw response if available in metadata
            raw_response = response.metadata['raw_response']
        else:
            # Assume it's already a raw response
            raw_response = response
            
        capability_calls = self._extract_capability_calls(raw_response)
        return capability_calls or []

    @abstractmethod
    def format_capability_results(self, results: list[Any]) -> list[dict[str, Any]]:
        """Format capability results for sending back to provider.
        
        This method encapsulates provider-specific logic for formatting
        CapabilityResult objects into the format expected by the provider
        for continuing the conversation.
        
        **Provider-Specific Responsibilities:**
        - Convert CapabilityResult objects to provider message format
        - Handle both successful results and errors
        - Format JSON content appropriately
        - Include required provider-specific fields
        
        Args:
            results: List of CapabilityResult objects to format
            
        Returns:
            List of formatted result dictionaries in provider format
            
        Example (OpenAI):
            >>> def format_capability_results(self, results):
            ...     formatted = []
            ...     for result in results:
            ...         content = json.dumps({"error": result.error}) if result.error else json.dumps(result.result)
            ...         formatted.append({
            ...             "tool_call_id": result.capability_call_id,
            ...             "role": "tool",
            ...             "content": content
            ...         })
            ...     return formatted
        
        Example (Bedrock):
            >>> def format_capability_results(self, results):
            ...     formatted = []
            ...     for result in results:
            ...         result_data = {"error": result.error} if result.error else result.result
            ...         formatted.append({
            ...             "toolResult": {
            ...                 "toolUseId": result.capability_call_id,
            ...                 "content": [{"json": result_data}]
            ...             }
            ...         })
            ...     return formatted
        """
        pass
    
    async def _aselect_with_router(self, router: Any, messages: list[Any] | str) -> str:
        """Ask a router which model to use for these messages.

        ``select_model`` of the router Port is ``async`` and takes a request, so the messages are wrapped in one and the result is awaited
        (a router that answers with the name itself is accepted).
        """
        from skye.base.messages import UserMessage

        if isinstance(messages, str):
            messages = [UserMessage(content=messages)]
        selection = router.select_model(CompleteRequest(messages=messages, model=self.default_model or ""))
        if inspect.isawaitable(selection):
            selection = await selection
        return selection  # type: ignore[no-any-return]

    @staticmethod
    def _resolved(request: CompleteRequest) -> CompleteRequest:
        """The request with its capabilities as a list: a registry or a ``ToolProvider`` gives its schemas (finding 17)."""
        capabilities = request.capabilities
        if capabilities is None or isinstance(capabilities, list):
            return request
        return dataclasses.replace(request, capabilities=capability_list(capabilities))

    def _provider_label(self) -> str:
        try:
            return str(self.get_model_info().get("provider", "unknown"))
        except Exception:
            return "unknown"

    def _wrap_failure(self, error: Exception, label: str) -> ProviderError:
        """A failure that is not a ``ProviderError`` (a bug in a transform, a socket error) as one; a timeout stays a timeout."""
        cls = ProviderTimeoutError if _is_timeout(error) else ProviderError
        return cls(
            f"{label}: {error}",
            provider=self._provider_label(),
            original_error=str(error),
            error_type=type(error).__name__,
        )

    # Requirement 33.9, decisions D81, D101
    def request_from_parts(self, parts: PromptParts, model: str | None = None, **options: Any) -> CompleteRequest:
        """The completion request for rendered prompt parts on this provider.

        The capabilities this adapter reports in ``get_model_info()`` decide whether the system text and the output schema travel
        in native fields or as text. ``complete(parts, model=...)`` calls it for you.

        Args:
            parts: The rendered prompt (``PromptParts`` from ``base``).
            model: The model identifier; the provider's default model when omitted.
            **options: Other request fields (``temperature``, ``max_tokens``, ``capabilities``, ...).

        Returns:
            The ``CompleteRequest`` to send.

        Raises:
            ValueError: If no model is given and the provider has no default model.
        """
        effective_model = model or self.default_model
        if effective_model is None:
            raise ValueError("Either 'model' or a default model is required for prompt parts")
        return request_from_parts(parts, model=effective_model, info=self.get_model_info(), **options)

    # Requirement 56.13
    def complete(
        self,
        messages: list[Any] | str | CompleteRequest | PromptParts | None = None,
        model: str | None = None,
        router: Any | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> CompleteResponse:
        """Execute synchronous completion.

        Runs :meth:`acomplete`, the one implementation, to the end (``run_sync``); inside a running event loop prefer
        :meth:`acomplete`.

        Supports both boto3-style direct calls and CompleteRequest objects.
        
        Boto3-style usage:
            >>> # With specific model
            >>> response = client.complete(
            ...     messages=[UserMessage("Hello")],
            ...     model="gpt-4"
            ... )
            >>>
            >>> # With router for load balancing
            >>> response = client.complete(
            ...     messages=[UserMessage("Hello")],
            ...     router=my_router
            ... )
        
        CompleteRequest usage (internal):
            >>> request = CompleteRequest(messages=[...], model="gpt-4")
            >>> response = provider.complete(request)
        
        Args:
            messages: List of SkyeMessage objects, string, CompleteRequest, or rendered PromptParts
            model: Model identifier (mutually exclusive with router)
            router: Router instance for load balancing (mutually exclusive with model)
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            **kwargs: Additional provider-specific parameters
            
        Returns:
            CompleteResponse with the model's output
            
        Raises:
            ProviderError: If the provider API call fails
            ValueError: If required parameters are missing or both model and router provided
        """
        return run_sync(self.acomplete(messages, model, router, temperature, max_tokens, **kwargs))

    # Requirement 27.2
    @staticmethod
    def _parse_structured_output(request: CompleteRequest, response: CompleteResponse) -> None:
        """Validate the text of the response against the declared output schema and attach the result.

        The REST adapters return plain JSON text (no SDK ``parsed`` field), so the shape is checked here, once, for every provider;
        the schema is a dataclass, or any class with ``model_validate_json``.
        A result that does not conform raises ``ValidationError`` naming the field; it is not retried.
        """
        schema = getattr(request, "response_schema", None)
        if schema is None or response.structured_output is not None or not response.content:
            return
        if response.capability_calls:
            return  # the model asked for a capability: the structured answer comes in a later turn
        response.structured_output = parse_structured(schema, response.content)

    def _log_provider(self) -> str:
        """The provider name for the log: ``provider_name`` when the class has one, else the class name (``BedrockProvider``: ``bedrock``)."""
        return getattr(self, "provider_name", None) or type(self).__name__.removesuffix("Provider").lower()

    # Requirement 18.3
    @staticmethod
    def _emit(build: Callable[[], ModelInvocationEvent]) -> None:
        """Log a model invocation event with structured ``extra``, never an f-string.

        A start is DEBUG, an end INFO and a failure WARNING (a fallback may still serve the request). The event holds no
        message content. One correlation id ties the start, the end and the error of one call. Logging never breaks a call:
        if the event cannot be built or logged, that is noted at DEBUG and the call goes on.
        """
        try:
            event = build()
            level = {"start": logging.DEBUG, "end": logging.INFO, "error": logging.WARNING}[event.phase]
            logger.log(level, "model invocation", extra=event.log_extra())
        except Exception:
            logger.debug("model invocation event not logged", exc_info=True)

    def _emit_stream_end(
        self,
        request: CompleteRequest,
        correlation_id: str,
        finish_reason: str | None,
        last: StreamChunk | None,
        latency_ms: float,
    ) -> None:
        """The end event of a stream, with the last running count its chunks carried."""
        self._emit(
            lambda: model_invocation_summary(
                model=request.model,
                provider=self._log_provider(),
                correlation_id=correlation_id,
                finish_reason=finish_reason,
                usage=None if last is None else last.usage,
                cost=None if last is None else last.cost,
                latency_ms=latency_ms,
            )
        )

    def _price(self, model: str, usage: TokenUsage, exact: bool) -> dict[str, Any] | None:
        """The cost of ``usage`` (``pricing=`` of this client first, then the price table); ``None`` without a price."""
        return CostCalculator.breakdown(model, usage, self.pricing, exact=exact)

    @staticmethod
    def _estimated_prompt_tokens(request: CompleteRequest) -> int:
        """The tokens of the request messages by the counter of the model (a registered tokenizer, ``tiktoken`` or the estimate)."""
        return TokenCounter.count_message_tokens(list(request.messages or []), request.model)

    # Requirement 19.1
    def _account(self, request: CompleteRequest, response: CompleteResponse) -> None:
        """Put the cost in ``response.metadata["cost"]``.

        The provider's token count is used as it is. When it reported none (all zero), the tokens are estimated from the
        messages and the answer, ``response.usage`` takes the estimate, ``metadata["usage_estimated"]`` is true and the cost
        says ``exact`` false.
        """
        usage = response.usage
        exact = usage is not None and (usage.prompt_tokens > 0 or usage.completion_tokens > 0)
        if not exact:
            prompt = self._estimated_prompt_tokens(request)
            completion = TokenCounter.count_tokens(response.content or "", request.model)
            usage = TokenUsage(prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion)
            response.usage = usage
            response.metadata["usage_estimated"] = True
        cost = self._price(request.model, usage, exact)
        if cost is None and response.model and response.model != request.model:
            cost = self._price(response.model, usage, exact)  # the provider may name the model differently
        response.metadata["cost"] = cost

    async def _with_running_cost(
        self, request: CompleteRequest, chunks: AsyncGenerator[StreamChunk, None]
    ) -> AsyncGenerator[StreamChunk, None]:
        """Give every chunk the running tokens and cost of the call (``chunk.usage`` and ``chunk.cost``).

        The prompt is counted once, from the messages. The completion is counted from the text received so far. As soon as
        the provider reports a count (OpenAI with ``include_usage``, Anthropic, Bedrock and Gemini all do), that count
        replaces the estimate and the cost says ``exact`` true once both counts are the provider's. Only a chunk that costs
        tokens (it has text, or it brings the provider's count) changes the counter; any other chunk repeats the value of
        the one before it.
        """
        model = request.model
        text = ""
        prompt_estimate: int | None = None
        reported_prompt = reported_completion = 0
        usage: TokenUsage | None = None
        cost: dict[str, Any] | None = None
        async for chunk in chunks:
            if not isinstance(chunk, StreamChunk):
                yield chunk  # a provider that yields something else keeps its own chunks, with no counter
                continue
            brings_count = chunk.usage is not None
            if chunk.usage is not None:
                reported_prompt = chunk.usage.prompt_tokens or reported_prompt
                reported_completion = chunk.usage.completion_tokens or reported_completion
            if usage is None or chunk.delta or brings_count:
                text += chunk.delta
                if not reported_prompt and prompt_estimate is None:
                    prompt_estimate = self._estimated_prompt_tokens(request)
                prompt = reported_prompt or prompt_estimate or 0
                completion = reported_completion or TokenCounter.count_tokens(text, model)
                usage = TokenUsage(prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion)
                cost = self._price(model, usage, bool(reported_prompt and reported_completion))
            chunk.usage = None if usage is None else dataclasses.replace(usage)
            chunk.cost = None if cost is None else dict(cost)
            yield chunk

    # Requirement 59.2
    def _profile_info(self, provider: str, model: str | None = None) -> dict[str, Any]:
        """The ``info`` of the entry of ``model`` (the default model when omitted) in the profile registered for ``provider``.

        Empty when the provider has no profile or the profile has no entry for the model: the keys the adapter itself knows are then all there is.
        """
        from skye.base.plugins import get_registrar
        from skye.base.profile import find_model_profile

        entry = find_model_profile(get_registrar().get_profile(provider), model if model is not None else self.model or "")
        return dict(entry.info) if entry is not None else {}

    # decision D109
    def refuses_forced_choice(self, model: str) -> bool:
        """Whether ``model`` refuses a forced ``capability_choice`` (``"required"`` or a name).

        ``False`` here; an adapter whose provider has such models overrides it, reading ``supports_forced_capability_choice`` of the model's
        ``info`` in its profile. For those models the client emulates the forced choice (``skye.models.utilities.capability_choice``).
        """
        return False

    # D104, D109
    async def _acomplete_with_retry(self, request: CompleteRequest) -> CompleteResponse:
        """One completion, retried on a transient failure; health metrics are not tracked here.

        A forced capability choice that the model refuses is emulated. A retry is not counted
        as a separate failure: ``acomplete`` records the outcome once.
        """
        if forced_choice(request) and self.refuses_forced_choice(request.model):
            return await acomplete_emulated(request, self._acomplete_with_transport_retry, self._provider_label())
        return await self._acomplete_with_transport_retry(request)

    # D104
    async def _acomplete_with_transport_retry(self, request: CompleteRequest) -> CompleteResponse:
        """One completion, retried on a transient failure."""
        return await acall_with_retry(
            lambda: self._acomplete_once(request),
            max_retries=getattr(self, "max_retries", DEFAULT_MAX_RETRIES),
            sleep=getattr(self, "retry_sleep", None),
            base_wait=self.retry_base_wait,
            max_wait=self.retry_max_wait,
            name=f"{type(self).__name__}.complete",
        )

    async def _acomplete_once(self, request: CompleteRequest) -> CompleteResponse:
        """One attempt: transform, call, transform back. A ``ProviderError`` keeps its class (429, 5xx, 401, ...)."""
        try:
            provider_request = self._transform_request(request)
            provider_response = await self._acall_provider(provider_request)
            return self._transform_response(provider_response)
        except (ValidationError, ProviderError):
            # The caller's input is wrong, or the transport already said what failed: raise it as it is.
            raise
        except Exception as e:
            raise self._wrap_failure(e, "Provider call failed") from e

    # Requirement 56.13
    def stream(
        self,
        messages: list[Any] | str | CompleteRequest | PromptParts | None = None,
        model: str | None = None,
        router: Any | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> Iterator[StreamChunk]:
        """Execute streaming completion.

        Iterates :meth:`astream`, the one implementation, from sync code (``iterate_sync``): one worker thread runs it,
        and closing the iterator early stops it. Inside a running event loop prefer :meth:`astream`.

        Supports both boto3-style direct calls and CompleteRequest objects.
        
        Boto3-style usage:
            >>> # With specific model
            >>> for chunk in client.stream(
            ...     messages=[UserMessage("Hello")],
            ...     model="gpt-4"
            ... ):
            ...     print(chunk.delta, end="")
            >>>
            >>> # With router for load balancing
            >>> for chunk in client.stream(
            ...     messages=[UserMessage("Hello")],
            ...     router=my_router
            ... ):
            ...     print(chunk.delta, end="")
        
        CompleteRequest usage (internal):
            >>> request = CompleteRequest(messages=[...], model="gpt-4", stream=True)
            >>> for chunk in provider.stream(request):
            ...     print(chunk.delta, end="")
        
        Args:
            messages: List of SkyeMessage objects, string, CompleteRequest, or rendered PromptParts
            model: Model identifier (mutually exclusive with router)
            router: Router instance for load balancing (mutually exclusive with model)
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            **kwargs: Additional provider-specific parameters
            
        Yields:
            StreamChunk objects with incremental content
            
        Raises:
            ProviderError: If the provider API call fails
            ValueError: If required parameters are missing or both model and router provided
        """
        return iterate_sync(self.astream(messages, model, router, temperature, max_tokens, **kwargs))

    async def invoke(self, input: CompleteRequest) -> CompleteResponse:
        """Runnable Port entry point: one request in, one response out.

        Delegates to :meth:`acomplete`; satisfies ``Runnable`` structurally.
        """
        return await self.acomplete(input)

    async def ainvoke(self, input: CompleteRequest) -> CompleteResponse:
        """A thin alias of :meth:`invoke` (the ``x`` / ``ax`` pair users of other libraries try first)."""
        return await self.invoke(input)

    # D104
    async def acomplete(
        self,
        messages: list[Any] | str | CompleteRequest | PromptParts | None = None,
        model: str | None = None,
        router: Any | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> CompleteResponse:
        """Execute asynchronous completion: the one implementation (``complete`` runs it to the end).

        The request is checked, sent through ``_acall_provider`` with the retries, parsed and costed here, for every provider.

        Args:
            messages: List of SkyeMessage objects, string, CompleteRequest, or rendered PromptParts
            model: Model identifier (mutually exclusive with router)
            router: Router instance for load balancing (mutually exclusive with model)
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            **kwargs: Additional provider-specific parameters

        Returns:
            CompleteResponse with the model's output

        Raises:
            ProviderError: If the provider API call fails
            ValueError: If required parameters are missing or both model and router provided
        """
        # Handle polymorphic input
        if isinstance(messages, PromptParts):
            # Rendered prompt parts (D101): this model's capabilities choose native fields or text
            if router is not None:
                raise ValueError("Prompt parts need a 'model'; route first, then pass the chosen model")
            sampling: dict[str, Any] = {k: v for k, v in {"temperature": temperature, "max_tokens": max_tokens}.items() if v is not None}
            messages = self.request_from_parts(messages, model=model or self.default_model, **sampling, **kwargs)
        if isinstance(messages, CompleteRequest):
            request = messages
        else:
            # Convert to CompleteRequest
            if messages is None:
                raise ValueError("messages parameter is required")
            
            # Validate model/router parameters
            if model is not None and router is not None:
                raise ValueError("Cannot specify both 'model' and 'router' parameters")
            
            # Use provided model, router, or fall back to default
            effective_model = model or self.default_model
            
            if router is not None:
                # Router will select the model
                effective_model = await self._aselect_with_router(router, messages)
            elif effective_model is None:
                raise ValueError(
                    "Either 'model' or 'router' parameter is required"
                )
            
            # Convert string to UserMessage if needed
            if isinstance(messages, str):
                from skye.base.messages import UserMessage
                messages = [UserMessage(content=messages)]
            
            # Only what the caller set: an omitted temperature or max_tokens keeps the request default.
            sampling = {k: v for k, v in {"temperature": temperature, "max_tokens": max_tokens}.items() if v is not None}
            request = CompleteRequest(
                messages=messages,
                model=effective_model,
                **sampling,
                **kwargs,
            )
        
        offered = request.capabilities
        start_time = time.time()
        correlation_id = new_correlation_id()
        try:
            request = self._resolved(request)
            self._emit(lambda: model_invocation_start(request, provider=self._log_provider(), correlation_id=correlation_id))
            response = await self._acomplete_with_retry(request)
            self._parse_structured_output(request, response)
            self._account(request, response)

            # Attach capabilities to response for direct execution (the registry itself when one was given)
            if offered:
                response._capabilities = offered
            
            # Record success with latency (only on final success)
            latency_ms = (time.time() - start_time) * 1000
            self.health_metrics.record_success(latency_ms)
            self._emit(lambda: model_invocation_end(response, correlation_id=correlation_id, latency_ms=latency_ms))

            return response
        except Exception as e:
            # Record failure (only on final failure after all retries)
            self.health_metrics.record_failure()
            self._emit(
                lambda: model_invocation_error(
                    e, model=request.model, provider=self._log_provider(), correlation_id=correlation_id
                )
            )
            raise
    

    async def astream(
        self,
        messages: list[Any] | str | CompleteRequest | PromptParts | None = None,
        model: str | None = None,
        router: Any | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """Execute asynchronous streaming completion: the one implementation (``stream`` iterates it).

        Takes the same arguments as :meth:`stream`. When the caller stops early, the transport is closed and the end of the stream is
        logged as interrupted.

        Args:
            messages: List of SkyeMessage objects, string, CompleteRequest, or rendered PromptParts
            model: Model identifier (mutually exclusive with router)
            router: Router instance for load balancing (mutually exclusive with model)
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            **kwargs: Additional provider-specific parameters

        Yields:
            StreamChunk objects with incremental content

        Raises:
            ProviderError: If the provider API call fails
            ValueError: If required parameters are missing or both model and router provided
        """
        # Handle polymorphic input
        if isinstance(messages, PromptParts):
            # Rendered prompt parts (D101): this model's capabilities choose native fields or text
            if router is not None:
                raise ValueError("Prompt parts need a 'model'; route first, then pass the chosen model")
            sampling: dict[str, Any] = {k: v for k, v in {"temperature": temperature, "max_tokens": max_tokens}.items() if v is not None}
            messages = self.request_from_parts(messages, model=model or self.default_model, **sampling, **kwargs)
        if isinstance(messages, CompleteRequest):
            request = messages
        else:
            # Convert to CompleteRequest
            if messages is None:
                raise ValueError("messages parameter is required")
            
            # Validate model/router parameters
            if model is not None and router is not None:
                raise ValueError("Cannot specify both 'model' and 'router' parameters")
            
            # Use provided model, router, or fall back to default
            effective_model = model or self.default_model
            
            if router is not None:
                # Router will select the model
                effective_model = await self._aselect_with_router(router, messages)
            elif effective_model is None:
                raise ValueError(
                    "Either 'model' or 'router' parameter is required"
                )
            
            # Convert string to UserMessage if needed
            if isinstance(messages, str):
                from skye.base.messages import UserMessage
                messages = [UserMessage(content=messages)]
            
            sampling = {k: v for k, v in {"temperature": temperature, "max_tokens": max_tokens}.items() if v is not None}
            request = CompleteRequest(
                messages=messages,
                model=effective_model,
                **sampling,
                stream=True,
                **kwargs,
            )
        
        start_time = time.time()
        correlation_id = new_correlation_id()
        last: StreamChunk | None = None
        finish_reason: str | None = None
        ended = False
        try:
            request = self._resolved(request)
            self._emit(lambda: model_invocation_start(request, provider=self._log_provider(), correlation_id=correlation_id))
            async with aclosing(self._with_running_cost(request, self._astream_with_retry(request))) as chunks:
                async for chunk in chunks:
                    if isinstance(chunk, StreamChunk):
                        last = chunk
                        finish_reason = chunk.finish_reason or finish_reason
                    yield chunk

            # Record success with latency after all chunks are yielded
            latency_ms = (time.time() - start_time) * 1000
            self.health_metrics.record_success(latency_ms)
            ended = True
            self._emit_stream_end(request, correlation_id, finish_reason, last, latency_ms)
        except Exception as e:
            # Record failure (only on final failure after all retries)
            self.health_metrics.record_failure()
            ended = True
            self._emit(
                lambda: model_invocation_error(
                    e, model=request.model, provider=self._log_provider(), correlation_id=correlation_id
                )
            )
            raise
        finally:
            if not ended:
                # The caller stopped reading: the tokens used so far are still worth a record.
                self._emit_stream_end(
                    request, correlation_id, finish_reason or "interrupted", last, (time.time() - start_time) * 1000
                )

    # D104, D109
    async def _astream_with_retry(self, request: CompleteRequest) -> AsyncGenerator[StreamChunk, None]:
        """The stream, retried on a transient failure only before its first chunk.

        Once a chunk has reached the caller a failure is raised: the text cannot be taken back. A
        forced capability choice that the model refuses is sent emulated, with no check.
        """
        if forced_choice(request) and self.refuses_forced_choice(request.model):
            request, _ = emulated_request(request)
        attempt = 1
        while True:
            async with aclosing(self._astream_once(request)) as chunks:
                try:
                    first = await anext(chunks)
                except StopAsyncIteration:
                    return
                except ProviderError as error:
                    if not is_retryable(error) or attempt > getattr(self, "max_retries", DEFAULT_MAX_RETRIES):
                        raise
                    await sleep_for(
                        getattr(self, "retry_sleep", None),
                        retry_wait(error, attempt, base_wait=self.retry_base_wait, max_wait=self.retry_max_wait),
                    )
                    attempt += 1
                    continue
                yield first
                async for chunk in chunks:
                    yield chunk
                return

    async def _astream_once(self, request: CompleteRequest) -> AsyncGenerator[StreamChunk, None]:
        """One streaming attempt; a ``ProviderError`` keeps its class, another failure is wrapped."""
        try:
            provider_request = self._transform_request(request)
            provider_request["stream"] = True

            async with aclosing(self._acall_provider_stream(provider_request)) as events:
                async for chunk in events:
                    yield self._transform_stream_chunk(chunk)
        except (ValidationError, ProviderError):
            raise
        except Exception as e:
            raise self._wrap_failure(e, "Provider streaming failed") from e

    def get_health_metrics(self) -> dict[str, Any]:
        """Get health metrics for this provider.
        
        Returns health statistics including success rate, error rate, latency,
        and request counts.
        
        Returns:
            Dictionary containing health metrics with keys:
            - success_count: Number of successful requests
            - failure_count: Number of failed requests
            - total_requests: Total requests (success + failure)
            - success_rate: Success rate as decimal (0.0-1.0)
            - error_rate: Error rate as decimal (0.0-1.0)
            - average_latency_ms: Average latency in milliseconds
            - min_latency_ms: Minimum latency observed (None if no requests)
            - max_latency_ms: Maximum latency observed (None if no requests)
            - last_success_time: Unix timestamp of last successful request
            - last_failure_time: Unix timestamp of last failed request
            
        Example:
            >>> provider = OpenAIProvider(api_key="...")
            >>> # Make some requests...
            >>> metrics = provider.get_health_metrics()
            >>> print(f"Success rate: {metrics['success_rate']:.1%}")
            >>> print(f"Avg latency: {metrics['average_latency_ms']:.0f}ms")
        """
        return self.health_metrics.get_health_metrics()


# Requirement 56.13
class BaseEmbeddingProvider(VectorEncoderInterface, ABC):
    """Abstract base class for embedding providers.
    
    This class provides common functionality for all embedding provider
    implementations, including lazy client initialization and batch encoding.
    
    Subclasses must implement:
    - _initialize_client(): Create the provider-specific client
    - _aencode_batch_impl(): Encode multiple texts to vectors (async, the only form)
    - get_vector_dimension(): Return the vector dimension

    The sync ``encode`` and ``encode_batch`` are derived from the async methods (``run_sync``); health tracking is in
    ``aencode_batch``. A subclass that only defines ``_encode_batch_impl`` no longer instantiates.
    
    Example:
        >>> class OpenAIEmbeddingProvider(BaseEmbeddingProvider):
        ...     def _initialize_client(self):
        ...         import openai
        ...         return openai.OpenAI(api_key=self.config["api_key"])...
        ...     async def _aencode_batch_impl(self, texts):
        ...         response = await self.client.embeddings.create(
        ...             model=self.model,
        ...             input=texts
        ...         )
        ...         return [item.embedding for item in response.data]...
        ...     def get_vector_dimension(self):
        ...         return 1536
    """
    
    def __init__(self, model: str, **config: Any) -> None:
        """Initialize base embedding provider.
        
        Args:
            model: Model identifier (e.g., 'text-embedding-3-small')
            **config: Provider-specific configuration parameters
        """
        self.model = model
        self.config = config
        self._client = None
        self.health_metrics = HealthMetrics()
    
    @property
    def client(self) -> Any:
        """Lazy-load the provider client.
        
        The client is only initialized when first accessed, reducing startup
        time and memory usage.
        
        Returns:
            The provider-specific client instance
        """
        if self._client is None:
            self._client = self._initialize_client()
        return self._client
    
    @abstractmethod
    def _initialize_client(self) -> Any:
        """Initialize the provider-specific client.
        
        This method should create and return the provider's SDK client.
        It will be called lazily when the client is first accessed.
        
        Returns:
            The initialized provider client
            
        Example:
            >>> def _initialize_client(self):
            ...     import openai
            ...     return openai.OpenAI(api_key=self.config["api_key"])
        """
        pass
    
    async def aencode(self, text: str) -> list[float]:
        """Encode single text to vector asynchronously.
        
        This method uses aencode_batch() internally for consistency.
        Health metrics are NOT tracked here to avoid double counting
        (aencode_batch already tracks metrics).
        
        Args:
            text: The text to encode
            
        Returns:
            Vector representation of the text
        """
        results = await self.aencode_batch([text])
        return results[0]
    
    async def aencode_batch(self, texts: list[str]) -> list[list[float]]:
        """Encode multiple texts to vectors asynchronously.
        
        This method wraps _aencode_batch_impl() with health tracking.
        
        Args:
            texts: List of texts to encode
            
        Returns:
            List of vector representations
        """
        start_time = time.time()
        try:
            result = await self._aencode_batch_impl(texts)
            latency_ms = (time.time() - start_time) * 1000
            self.health_metrics.record_success(latency_ms)
            return result
        except Exception as e:
            self.health_metrics.record_failure()
            raise
    
    @abstractmethod
    async def _aencode_batch_impl(self, texts: list[str]) -> list[list[float]]:
        """Encode multiple texts to vectors (implementation, async).

        Subclasses must implement this method; ``aencode_batch`` wraps it with health tracking and the sync ``encode_batch`` runs it to the
        end. A blocking call (``urllib``) goes through ``asyncio.to_thread``.

        Args:
            texts: List of texts to encode

        Returns:
            List of vector representations
        """

    # D110
    def _profile_dimension(self, provider: str) -> int:
        """The vector dimension of ``self.model``, from ``info["vector_dimension"]`` of its entry in the profile of ``provider``.

        Raises:
            ValueError: The provider has no profile, or the profile has no entry for the model with a dimension.
        """
        from skye.base.plugins import get_registrar
        from skye.base.profile import find_model_profile

        entry = find_model_profile(get_registrar().get_profile(provider), self.model)
        dimension = entry.info.get("vector_dimension") if entry is not None else None
        if dimension is None:
            raise ValueError(f"Unknown model: {self.model}")
        return int(dimension)

    @staticmethod
    def _profile_api_base(provider: str) -> str:
        """The default endpoint of ``provider`` from its profile (``default_api_base``)."""
        from skye.base.exceptions import ConfigurationError
        from skye.base.plugins import get_registrar

        profile = get_registrar().get_profile(provider)
        if profile is None or not profile.default_api_base:
            raise ConfigurationError(f"the provider {provider!r} has no default endpoint in its profile; pass api_base")
        return str(profile.default_api_base)

    @abstractmethod
    def get_vector_dimension(self) -> int:
        """Return the dimension of vectors produced by this encoder.
        
        Returns:
            The vector dimension size
            
        Example:
            >>> def get_vector_dimension(self):
            ...     return 1536  # For text-embedding-3-small
        """
        pass
    
    def get_health_metrics(self) -> dict[str, Any]:
        """Get health metrics for this embedding provider.
        
        Returns health statistics including success rate, error rate, latency,
        and request counts.
        
        Returns:
            Dictionary containing health metrics with keys:
            - success_count: Number of successful encoding requests
            - failure_count: Number of failed encoding requests
            - total_requests: Total requests (success + failure)
            - success_rate: Success rate as decimal (0.0-1.0)
            - error_rate: Error rate as decimal (0.0-1.0)
            - average_latency_ms: Average latency in milliseconds
            - min_latency_ms: Minimum latency observed (None if no requests)
            - max_latency_ms: Maximum latency observed (None if no requests)
            - last_success_time: Unix timestamp of last successful request
            - last_failure_time: Unix timestamp of last failed request
            
        Example:
            >>> provider = OpenAIEmbeddingProvider(model="text-embedding-3-small")
            >>> # Make some encoding requests...
            >>> metrics = provider.get_health_metrics()
            >>> print(f"Success rate: {metrics['success_rate']:.1%}")
        """
        return self.health_metrics.get_health_metrics()
