# Requirement 18.3
"""The structured log event of a model invocation, and the correlation id of its parts.

``base`` owns the shape; the code that emits it lives in ``models`` and
``observe``.
An event goes to the standard ``logging`` module as ``extra={...}`` (never an f-string), and to a
telemetry plugin through ``ObserverInterface.log_event`` / ``EventHandlerInterface``.

Example:
    >>> import logging
    >>> from skye.base.completion import CompleteRequest
    >>> from skye.base.log_event import model_invocation_start
    >>> from skye.base.messages import UserMessage
    >>>
    >>> request = CompleteRequest(messages=[UserMessage(content="Hi")], model="gpt-4")
    >>> event = model_invocation_start(request, provider="openai")
    >>> logging.getLogger("skye.models").info("model invocation", extra=event.log_extra())
"""

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from skye.base.completion import CompleteRequest, CompleteResponse, TokenUsage
from skye.base.interfaces.observer import EventType
from skye.base.validated import Validated, field, validated

_EVENT_TYPES = {
    "start": EventType.MODEL_INVOKE_START,
    "end": EventType.MODEL_INVOKE_END,
    "error": EventType.MODEL_INVOKE_ERROR,
}


def new_correlation_id() -> str:
    """A new correlation id: one per invocation, shared by its start, end and error events."""
    return str(uuid4())


@validated
class ModelInvocationEvent(Validated):
    """One structured log event of a model invocation.

    Attributes:
        phase: ``start`` (request sent), ``end`` (response received) or ``error``.
        model: The model identifier.
        provider: The provider name.
        correlation_id: Ties the events of one invocation together (and to the HTTP header named by
            ``SkyeConfig.correlation_id_header``).
        request: Request details: number of messages, temperature, max tokens, stream.
        response: Response details: finish reason, token usage, cost, latency in milliseconds.
        error: The error message, for the ``error`` phase.
        timestamp: When the event was created.
    """

    phase: Literal["start", "end", "error"]
    model: str
    provider: str
    correlation_id: str = field(default_factory=new_correlation_id)
    request: dict[str, Any] = field(default_factory=dict)
    response: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def event_type(self) -> EventType:
        """The ``EventType`` a telemetry hook receives for this event."""
        return _EVENT_TYPES[self.phase]

    def log_extra(self) -> dict[str, Any]:
        """The event as the ``extra`` of a log call, each key prefixed ``skye_``."""
        return {f"skye_{key}": value for key, value in self.to_dict().items()}


def _request_details(request: CompleteRequest) -> dict[str, Any]:
    """The loggable details of a request (no message content: it may hold personal data)."""
    return {
        "messages": len(request.messages) if request.messages is not None else 0,
        "prompt": request.prompt,
        "temperature": request.temperature,
        "max_tokens": request.max_tokens,
        "stream": request.stream,
    }


def model_invocation_start(
    request: CompleteRequest, *, provider: str, correlation_id: str | None = None
) -> ModelInvocationEvent:
    """The event for a request about to be sent.

    Args:
        request: The completion request.
        provider: The provider name.
        correlation_id: The id to reuse; a new one is generated when omitted.
    """
    return ModelInvocationEvent(
        phase="start",
        model=request.model,
        provider=provider,
        correlation_id=correlation_id or new_correlation_id(),
        request=_request_details(request),
    )


def model_invocation_summary(
    *,
    model: str,
    provider: str,
    correlation_id: str,
    finish_reason: str | None,
    usage: TokenUsage | None,
    cost: dict[str, Any] | None = None,
    latency_ms: float | None = None,
) -> ModelInvocationEvent:
    """The ``end`` event from its parts, for a call that has no ``CompleteResponse`` (a stream).

    Args:
        model: The model identifier.
        provider: The provider name.
        correlation_id: The id of the start event.
        finish_reason: Why the generation stopped, or ``None``.
        usage: The tokens of the call, or ``None`` when none were counted.
        cost: The cost of the call (``response.metadata["cost"]``), or ``None``.
        latency_ms: How long the invocation took, in milliseconds.
    """
    return ModelInvocationEvent(
        phase="end",
        model=model,
        provider=provider,
        correlation_id=correlation_id,
        response={
            "finish_reason": finish_reason,
            "prompt_tokens": None if usage is None else usage.prompt_tokens,
            "completion_tokens": None if usage is None else usage.completion_tokens,
            "total_tokens": None if usage is None else usage.total_tokens,
            "cost": cost,
            "latency_ms": latency_ms,
        },
    )


def model_invocation_end(
    response: CompleteResponse, *, correlation_id: str, latency_ms: float | None = None
) -> ModelInvocationEvent:
    """The event for a response received.

    Args:
        response: The completion response.
        correlation_id: The id of the start event.
        latency_ms: How long the invocation took, in milliseconds.
    """
    return model_invocation_summary(
        model=response.model,
        provider=response.provider,
        correlation_id=correlation_id,
        finish_reason=response.finish_reason,
        usage=response.usage,
        cost=response.metadata.get("cost"),
        latency_ms=latency_ms,
    )


def model_invocation_error(
    error: BaseException, *, model: str, provider: str, correlation_id: str
) -> ModelInvocationEvent:
    """The event for an invocation that failed.

    Args:
        error: The exception.
        model: The model identifier.
        provider: The provider name.
        correlation_id: The id of the start event.
    """
    return ModelInvocationEvent(
        phase="error",
        model=model,
        provider=provider,
        correlation_id=correlation_id,
        error=f"{type(error).__name__}: {error}",
    )
