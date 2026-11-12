"""Reading what the endpoint sends back: a complete response and one chunk of a stream."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from skye.base.completion import CompleteResponse, StreamChunk, TokenUsage
from skye.models.cost import usage_of

if TYPE_CHECKING:
    from skye.models.utilities.openai_compatible.provider import OpenAICompatibleProvider


def response_metadata(
    provider: OpenAICompatibleProvider, response: Any, tool_calls: Any
) -> dict[str, Any]:
    """Response metadata; ``system_fingerprint`` only where the endpoint reports it."""
    metadata: dict[str, Any] = {}
    if provider.reports_fingerprint:
        metadata["system_fingerprint"] = getattr(response, "system_fingerprint", None)
    metadata["tool_calls"] = tool_calls
    return metadata


def transform_response(provider: OpenAICompatibleProvider, response: Any) -> CompleteResponse:
    """Transform OpenAI response to CompleteResponse.

    ``provider`` supplies the capability-call extraction, the provider label and the metadata (a subclass may override them).

    Args:
        provider: The provider that reads the response
        response: The OpenAI response object

    Returns:
        CompleteResponse in skye format
    """
    choice = response.choices[0]
    message = choice.message

    # Parse structured output if present
    structured_output = None
    if hasattr(message, "parsed") and message.parsed:
        structured_output = message.parsed

    # Extract capability calls using internal method
    capability_calls_list = provider._extract_capability_calls(response)

    # Store raw tool calls in metadata for compatibility
    tool_calls_metadata = None
    if hasattr(message, "tool_calls") and message.tool_calls:
        tool_calls_metadata = [
            {
                "id": tc.id,
                "type": tc.type,
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in message.tool_calls
        ]

    return CompleteResponse(
        id=response.id,
        model=response.model,
        provider=provider.provider_name,
        content=message.content or "",
        structured_output=structured_output,
        role="assistant",
        finish_reason=choice.finish_reason,
        usage=TokenUsage(
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            total_tokens=response.usage.total_tokens,
        ),
        capability_calls=capability_calls_list,
        created_at=datetime.fromtimestamp(response.created, tz=timezone.utc),
        metadata=provider._response_metadata(response, tool_calls_metadata),
    )


def transform_stream_chunk(chunk: Any) -> StreamChunk:
    """Transform OpenAI stream chunk to StreamChunk.

    Args:
        chunk: The OpenAI stream chunk

    Returns:
        StreamChunk in skye format
    """
    # The API omits keys it has nothing to say about: the last chunk has `"delta": {}`, and a usage-only chunk has no choices.
    chunk_id = getattr(chunk, "id", "")
    choices = getattr(chunk, "choices", None) or []
    # With include_usage the last chunk has no choices and the usage of the whole request; the others carry null.
    raw_usage = getattr(chunk, "usage", None)
    usage = (
        usage_of(
            getattr(raw_usage, "prompt_tokens", None),
            getattr(raw_usage, "completion_tokens", None),
            getattr(raw_usage, "total_tokens", None),
        )
        if raw_usage is not None
        else None
    )
    if not choices:
        return StreamChunk(id=chunk_id, delta="", finish_reason=None, index=0, usage=usage)
    choice = choices[0]
    delta = getattr(choice, "delta", None)

    return StreamChunk(
        id=chunk_id,
        delta=(getattr(delta, "content", None) or "") if delta is not None else "",
        finish_reason=getattr(choice, "finish_reason", None),
        index=getattr(choice, "index", 0),
        usage=usage,
    )
