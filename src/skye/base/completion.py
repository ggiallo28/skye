"""Completion request and response models for Skye.

This module provides dataclass models for LLM completion requests and responses,
including support for streaming, structured outputs, and token usage tracking.

Example:
    >>> from skye.base.completion import CompleteRequest, TokenUsage
    >>> from skye.base.messages import UserMessage
    >>>
    >>> request = CompleteRequest(
    ...     messages=[UserMessage(content="Hello")],
    ...     model="gpt-4",
    ...     temperature=0.7
    ... )
    >>> request.temperature
    0.7
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from skye.base.exceptions import ValidationError
from skye.base.capability_execution import (
    arun_capability_call,
    find_capability,
    run_capability_call,
)
from skye.base.messages import CapabilityMessage, SkyeMessage
from skye.base.prompt_parts import OutputSchema
from skye.base.validated import Validated, field, validated

if TYPE_CHECKING:
    from skye.base.capability_schema import CapabilityRegistryLike
    from skye.base.interfaces.capability import CapabilityInterface


# Requirement 2
@validated
class CapabilityCall(Validated):
    """A capability call requested by an LLM: the one call type, saved as id, name and arguments.

    When an LLM decides to invoke a capability, it generates a capability call containing the capability name and arguments.
    The call is provider-agnostic and serialisable (``dump(call)`` holds only ``id``, ``name`` and ``arguments``). A call that came
    from a ``CompleteResponse`` can also run itself with ``execute()``: it uses the capabilities the response carries, which are
    kept outside the saved fields, so saving a call never saves a live capability.

    Lives in base so provider adapters in ``models`` need no import of the tools Component;
    ``skye.tools.capability_models`` re-exports it.

    Attributes:
        id: Unique identifier for this capability call (from the provider)
        name: Name of the capability to invoke
        arguments: Dictionary of arguments to pass to the capability

    Example:
        >>> capability_call = CapabilityCall(
        ...     id="call_123",
        ...     name="weather.get_current",
        ...     arguments={"location": "San Francisco"}
        ... )
        >>> capability_call.execute().is_error  # no capability is attached to this call
        True
    """

    id: str = field(description="Unique identifier for this capability call from the provider")
    name: str = field(description="Name of the capability to invoke")
    arguments: dict[str, Any] = field(
        default_factory=dict, description="Arguments to pass to the capability"
    )
    # Internal: where to find the capability (a list or a registry), set by the response; never saved, never an argument
    _capabilities: Any = field(default=None, init=False, repr=False, compare=False)

    def execute(self, **override_arguments: Any) -> CapabilityMessage:
        """Run the call and return a ``CapabilityMessage``. It never raises: a failure is a message with the status ``error``.

        ``override_arguments`` are merged over the arguments the model chose.
        """
        capability = find_capability(self._capabilities, self.name)
        return run_capability_call(capability, self.id, self.name, {**self.arguments, **override_arguments})

    async def aexecute(self, **override_arguments: Any) -> CapabilityMessage:
        """The asynchronous form of ``execute``: it awaits ``capability.aexecute``. It never raises."""
        capability = find_capability(self._capabilities, self.name)
        return await arun_capability_call(capability, self.id, self.name, {**self.arguments, **override_arguments})


@validated
class TokenUsage(Validated):
    """Token usage statistics for a completion request.

    Tracks the number of tokens used in the prompt, completion, and total.
    This information is essential for cost tracking and rate limiting.

    Attributes:
        prompt_tokens: Number of tokens in the input prompt.
        completion_tokens: Number of tokens in the generated completion.
        total_tokens: Total tokens used (prompt + completion).

    Example:
        >>> usage = TokenUsage(
        ...     prompt_tokens=10,
        ...     completion_tokens=20,
        ...     total_tokens=30
        ... )
        >>> usage.total_tokens
        30
    """

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


# decision D109
@validated
class CompleteRequest(Validated):
    """Request for model completion.

    Represents a request to an LLM provider with all necessary parameters
    including messages, model configuration, and optional structured output schema.

    **Polymorphic Input Support:**
    - **Base Skye**: Use `messages` parameter with list of SkyeMessage objects
    - **With skyeai[prompts]**: Use `prompt` parameter with template name and variables

    The interface accepts either messages OR prompt, making it work seamlessly
    with or without the optional prompts package installed.

    Attributes:
        messages: List of messages in the conversation (base Skye).
        prompt: Prompt template name (requires skyeai[prompts]).
        prompt_variables: Variables for prompt template rendering.
        model: Model identifier (e.g., 'gpt-4', 'claude-3-sonnet').
        temperature: Sampling temperature (0.0-2.0). Higher values make output more random.
        max_tokens: Maximum number of tokens to generate.
        top_p: Nucleus sampling parameter (0.0-1.0).
        stop: List of sequences that will stop generation.
        stream: Whether to stream the response.
        capabilities: The capabilities available to the model: a list of capabilities, or a
            ``CapabilityRegistry`` or any ``ToolProvider`` (the adapter offers its schemas).
        capability_choice: How the model should choose capabilities ('auto', 'required', or specific capability name).
        force_choice: For a model that refuses a forced choice, send only the capability named in
            ``capability_choice`` (allowed before the model's first answer only).
        response_format: Format specification for structured outputs.
        response_schema: Class that describes the structured output (for example a pydantic model
            or a dataclass), or an ``OutputSchema`` from rendered prompt parts (its reply is a ``dict``);
            the adapter validates the reply with it.
        metadata: Additional metadata for the request.

    Example (Base Skye):
        >>> from skye.base.messages import UserMessage
        >>> request = CompleteRequest(
        ...     messages=[UserMessage(content="What is 2+2?")],
        ...     model="gpt-4",
        ...     temperature=0.7
        ... )
        >>> request.model
        'gpt-4'

    Example (With skyeai[prompts]):
        >>> # Using prompt templates (requires skyeai[prompts])
        >>> request = CompleteRequest(
        ...     prompt="math_solver",
        ...     prompt_variables={"problem": "What is 2+2?"},
        ...     model="gpt-4"
        ... )
        >>> request.prompt
        'math_solver'

    Example (With skyeai[capabilities]):
        >>> # Using capabilities (requires skyeai[capabilities])
        >>> from skye.tools import LocalFunctionCapability
        >>>
        >>> def get_weather(location: str) -> str:
        ...     return f"Weather for {location}"
        >>>
        >>> capability = LocalFunctionCapability(
        ...     func=get_weather,
        ...     name="get_weather",
        ...     description="Get weather for a location"
        ... )
        >>>
        >>> request = CompleteRequest(
        ...     messages=[UserMessage(content="What's the weather in NYC?")],
        ...     model="gpt-4",
        ...     capabilities=[capability],
        ...     capability_choice="auto"
        ... )
        >>> len(request.capabilities)
        1

    """

    # Polymorphic input: either messages OR prompt
    messages: list[SkyeMessage] | None = None
    prompt: str | None = None  # Template name (requires skyeai[prompts])
    prompt_variables: dict[str, Any] = field(default_factory=dict)

    model: str
    temperature: float = field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int | None = field(default=None, gt=0)
    top_p: float = field(default=1.0, ge=0.0, le=1.0)
    stop: list[str] | None = None
    stream: bool = False
    # Capabilities can be provided as:
    # 1. List of CapabilityInterface objects (direct, no registry needed)
    # 2. A CapabilityRegistry or any ToolProvider (its schemas are offered)
    capabilities: Any | None = None  # list of CapabilityInterface, a CapabilityRegistry or a ToolProvider
    capability_choice: str | None = None  # "auto", "required", or specific capability name
    force_choice: bool = False  # D109: when the model refuses a forced choice, send only the named capability
    response_format: dict[str, Any] | None = None
    response_schema: type | OutputSchema | None = None  # a dataclass (the standard), a user's pydantic model, or an OutputSchema of prompt parts (D101)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate the fields, then that exactly one of messages and prompt is provided."""
        super().__post_init__()
        choice = self.capability_choice
        if choice is not None and choice not in ("auto", "required") and not choice.strip():
            raise ValidationError(
                "capability_choice must be 'auto', 'required', or a non-empty capability name",
                field="capability_choice",
                value=choice,
            )
        if self.messages is None and self.prompt is None:
            raise ValidationError(
                "Either 'messages' or 'prompt' must be provided", field="messages", value=None
            )
        if self.messages is not None and self.prompt is not None:
            raise ValidationError(
                "Cannot provide both 'messages' and 'prompt' - use one or the other",
                field="prompt",
                value=self.prompt,
            )


# decision D109
@validated
class CompleteResponse(Validated):
    """Response from model completion.

    Represents the response from an LLM provider, including the generated content,
    token usage, optional structured output, and capability calls.

    Attributes:
        id: Unique identifier for the response.
        model: Model identifier that generated the response.
        provider: Provider name (e.g., 'openai', 'anthropic', 'bedrock').
        content: The generated text content.
        structured_output: Parsed structured output if response_schema was provided.
        role: Role of the responder (typically 'assistant').
        finish_reason: Reason the generation stopped ('stop', 'length', 'capability_calls', etc.).
        usage: Token usage statistics.
        capability_calls: List of capability calls requested by the model (requires skyeai[capabilities]).
        created_at: Timestamp when the response was created.
        added_messages: Messages Skye appended to the request (the instruction of an emulated forced choice); add them to the history to keep it append-only.
        metadata: Additional metadata about the response.

    Example (Basic Response):
        >>> from datetime import datetime, timezone
        >>> response = CompleteResponse(
        ...     id="resp_123",
        ...     model="gpt-4",
        ...     provider="openai",
        ...     content="The answer is 4.",
        ...     role="assistant",
        ...     finish_reason="stop",
        ...     usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        ...     created_at=datetime.now(timezone.utc)
        ... )
        >>> response.get_output()
        'The answer is 4.'

    Example (With Capability Calls):
        >>> from skye.completion import CapabilityCall
        >>> response = CompleteResponse(
        ...     model="gpt-4",
        ...     provider="openai",
        ...     content="",
        ...     role="assistant",
        ...     finish_reason="capability_calls",
        ...     usage=TokenUsage(prompt_tokens=50, completion_tokens=20, total_tokens=70),
        ...     capability_calls=[
        ...         CapabilityCall(
        ...             id="call_123",
        ...             name="weather.get_current",
        ...             arguments={"location": "San Francisco"}
        ...         )
        ...     ]
        ... )
        >>> response.has_capability_calls()
        True
        >>> # Execute capability calls (requires skyeai[capabilities])
        >>> from skye.tools.registry import CapabilityRegistry
        >>> registry = CapabilityRegistry.get_instance()
        >>> results = response.execute_capability_calls(registry)  # doctest: +SKIP
    """

    id: str = field(default_factory=lambda: str(uuid4()))
    model: str
    provider: str
    content: str
    structured_output: Any | None = None  # an instance of response_schema
    role: str = "assistant"
    finish_reason: str
    usage: TokenUsage
    capability_calls: list[CapabilityCall] | None = None
    added_messages: list[Any] = field(default_factory=list)  # D109: messages Skye appended; keep them in the history
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)
    
    # Internal: the capabilities of the request, kept to execute the calls; not an argument
    _capabilities: "list[CapabilityInterface] | CapabilityRegistryLike | None" = field(default=None, init=False, repr=False, compare=False)

    def get_output(self) -> Any:
        """Get the output - structured if available, otherwise text content.

        Returns:
            The structured output if available, otherwise the text content.

        Example:
            >>> # With text content
            >>> response = CompleteResponse(
            ...     model="gpt-4",
            ...     provider="openai",
            ...     content="Hello",
            ...     finish_reason="stop",
            ...     usage=TokenUsage(prompt_tokens=5, completion_tokens=2, total_tokens=7)
            ... )
            >>> response.get_output()
            'Hello'
            >>>
            >>> # With structured output
            >>>             >>> @dataclass
            ... class Person:
            ...     name: str
            >>> person = Person(name="Alice")
            >>> response.structured_output = person
            >>> response.get_output().name
            'Alice'
        """
        return self.structured_output if self.structured_output else self.content

    def to_message(self) -> "SkyeMessage":
        """Convert the response to an AssistantMessage for conversation continuation.

        Returns:
            AssistantMessage containing the response content and capability calls.

        Example:
            >>> response = CompleteResponse(
            ...     model="gpt-4",
            ...     provider="openai",
            ...     content="Let me check that for you.",
            ...     finish_reason="capability_calls",
            ...     usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            ...     capability_calls=[
            ...         CapabilityCall(id="call_1", name="get_weather", arguments={"city": "NYC"})
            ...     ]
            ... )
            >>> msg = response.to_message()
            >>> msg.role
            'assistant'
            >>> len(msg.capability_calls)
            1
        """
        from skye.base.messages import AssistantMessage

        # Convert CapabilityCall objects to dicts for AssistantMessage
        capability_calls_dicts = []
        if self.capability_calls:
            for call in self.capability_calls:
                capability_calls_dicts.append({
                    "id": call.id,
                    "name": call.name,
                    "arguments": call.arguments
                })

        return AssistantMessage(
            content=self.content,
            capability_calls=capability_calls_dicts
        )

    def has_capability_calls(self) -> bool:
        """Check if the response contains capability calls.

        Returns:
            True if the response contains one or more capability calls, False otherwise.

        Example:
            >>> from skye.completion import CapabilityCall
            >>> response = CompleteResponse(
            ...     model="gpt-4",
            ...     provider="openai",
            ...     content="",
            ...     finish_reason="capability_calls",
            ...     usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            ...     capability_calls=[
            ...         CapabilityCall(id="call_1", name="get_weather", arguments={"city": "NYC"})
            ...     ]
            ... )
            >>> response.has_capability_calls()
            True
            >>>
            >>> response_no_capabilities = CompleteResponse(
            ...     model="gpt-4",
            ...     provider="openai",
            ...     content="Hello",
            ...     finish_reason="stop",
            ...     usage=TokenUsage(prompt_tokens=5, completion_tokens=2, total_tokens=7)
            ... )
            >>> response_no_capabilities.has_capability_calls()
            False
        """
        return self.capability_calls is not None and len(self.capability_calls) > 0
    
    def __setattr__(self, name: str, value: Any) -> None:
        super().__setattr__(name, value)
        if name in ("_capabilities", "capability_calls"):
            self._attach_capabilities()

    def __post_init__(self) -> None:
        super().__post_init__()
        self._attach_capabilities()

    def _attach_capabilities(self) -> None:
        """Give every call the capabilities of the request, so ``call.execute()`` can find its capability."""
        for call in self.__dict__.get("capability_calls") or []:
            call._capabilities = self.__dict__.get("_capabilities")

    @property
    def text(self) -> str:
        """The text of the reply: a read-only alias of ``content`` (the name users of other libraries try first)."""
        return self.content

    def execute_capability_calls(
        self,
        registry: "CapabilityRegistryLike | None" = None,
        argument_overrides: dict[str, dict[str, Any]] | None = None,
    ) -> list["SkyeMessage"]:
        """Run every capability call of the response and return one ``CapabilityMessage`` per call.

        The messages can be added to the conversation for the next completion. It uses the capabilities of the original request,
        or ``registry`` when the request had none. A call that fails gives a message with the status ``error``; nothing is raised
        for a failing call. ``aexecute_capability_calls`` is the asynchronous form.

        Args:
            registry: A capability registry, used when the request carried no capabilities.
            argument_overrides: Arguments merged over the model's, per call id or per capability name; overrides win.

        Returns:
            One ``CapabilityMessage`` per call, in order.

        Raises:
            ValueError: If the response has no capability calls, or if there is neither request capabilities nor a registry.

        Example:
            >>> response = client.complete(
            ...     messages=[UserMessage(content="What's the weather in San Francisco?")],
            ...     model="gpt-4",
            ...     capabilities=[weather_capability]
            ... )  # doctest: +SKIP
            >>> if response.has_capability_calls():
            ...     capability_messages = response.execute_capability_calls()  # doctest: +SKIP
        """
        source = self._execution_source(registry)
        return [
            run_capability_call(
                find_capability(source, call.name), call.id, call.name, self._arguments_of(call, argument_overrides)
            )
            for call in self.capability_calls or []
        ]

    async def aexecute_capability_calls(
        self,
        registry: "CapabilityRegistryLike | None" = None,
        argument_overrides: dict[str, dict[str, Any]] | None = None,
    ) -> list["SkyeMessage"]:
        """The asynchronous form of ``execute_capability_calls``: it awaits ``capability.aexecute`` for each call, in order."""
        source = self._execution_source(registry)
        return [
            await arun_capability_call(
                find_capability(source, call.name), call.id, call.name, self._arguments_of(call, argument_overrides)
            )
            for call in self.capability_calls or []
        ]

    def _execution_source(self, registry: "CapabilityRegistryLike | None") -> Any:
        if not self.has_capability_calls():
            raise ValueError("Response has no capability calls to execute")
        source = self._capabilities or registry
        if not source:
            raise ValueError(
                "No capabilities available. Either pass capabilities in the request "
                "or provide a CapabilityRegistry instance."
            )
        return source

    @staticmethod
    def _arguments_of(call: CapabilityCall, overrides: dict[str, dict[str, Any]] | None) -> dict[str, Any]:
        """The model's arguments with the overrides given for the call id or, failing that, for its capability name."""
        arguments = dict(call.arguments)
        if overrides:
            arguments.update(overrides.get(call.name, {}))
            arguments.update(overrides.get(call.id, {}))
        return arguments


@validated
class StreamChunk(Validated):
    """A chunk from a streaming response.

    Represents a single chunk of data received during streaming completion.
    Multiple chunks are received sequentially to build the complete response.

    Attributes:
        id: Unique identifier for the stream.
        delta: The incremental content in this chunk.
        finish_reason: Reason the generation stopped (only set in final chunk).
        index: Index of this chunk in the stream sequence.
        usage: A running counter of the tokens of the call so far, or ``None`` when it is not
            counted. Chunks a model client yields carry it; a chunk that costs no token repeats
            the value of the chunk before it. It is an estimate until the provider reports its own
            numbers, then it is the provider's count.
        cost: The running cost of the call, in the shape of ``response.metadata["cost"]``
            (``prompt``, ``completion``, ``total``, ``currency``, ``exact``), or ``None`` when the
            model has no price.

    Example:
        >>> chunk = StreamChunk(
        ...     id="stream_123",
        ...     delta="Hello",
        ...     index=0
        ... )
        >>> chunk.delta
        'Hello'
        >>>
        >>> # Final chunk
        >>> final_chunk = StreamChunk(
        ...     id="stream_123",
        ...     delta="",
        ...     finish_reason="stop",
        ...     index=5
        ... )
        >>> final_chunk.finish_reason
        'stop'
    """

    id: str
    delta: str
    finish_reason: str | None = None
    index: int = 0
    usage: TokenUsage | None = None
    cost: dict[str, Any] | None = None
