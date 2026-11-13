# D110
"""Reading what the Anthropic Messages endpoint returns: a response, and each event of a stream.

Raises: nothing of its own; a malformed response raises whatever attribute error the missing field causes, as the provider always did.
Missing: absent optional fields (``stop_sequence``, ``usage`` of a stream event, the text of a delta) become ``None`` or an empty string.
Concurrency: pure functions, safe from many threads.
"""

import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from skye.base.completion import CompleteResponse, StreamChunk, TokenUsage
from skye.models.cost import usage_of
from skye.models.utilities.structured import STRUCTURED_TOOL


def transform_response(
    response: Any,
    provider_name: str,
    plain: Callable[[Any], Any],
    extract_capability_calls: Callable[[Any], list[Any] | None],
) -> CompleteResponse:
    """Transform Anthropic response to CompleteResponse.

    Args:
        response: The Anthropic response object
        provider_name: The label reported in the response (``provider_name`` of the provider)
        plain: Turns a tool ``input`` into a plain dict (the provider's ``_plain``)
        extract_capability_calls: Reads the requested capability calls (the provider's own method)

    Returns:
        CompleteResponse in skye format
    """
    # Extract content
    content_text = ""
    capability_calls_metadata = []

    for content_block in response.content:
        if content_block.type == "text":
            content_text += content_block.text
        elif content_block.type == "tool_use" and content_block.name == STRUCTURED_TOOL:
            # The structured answer: its input is the JSON the declared schema describes
            content_text = json.dumps(plain(content_block.input))
        elif content_block.type == "tool_use":
            # Store in metadata for compatibility
            capability_calls_metadata.append(
                {
                    "id": content_block.id,
                    "type": "function",
                    "function": {
                        "name": content_block.name,
                        "arguments": plain(content_block.input),
                    },
                }
            )

    # Extract capability calls using internal method
    capability_calls_list = extract_capability_calls(response)

    # Create timestamp from current time (Anthropic doesn't provide created timestamp)
    created_at = datetime.now(timezone.utc)

    return CompleteResponse(
        id=response.id,
        model=response.model,
        provider=provider_name,
        content=content_text,
        structured_output=None,  # Anthropic doesn't have native structured output
        role="assistant",
        finish_reason=response.stop_reason,
        usage=TokenUsage(
            prompt_tokens=response.usage.input_tokens,
            completion_tokens=response.usage.output_tokens,
            total_tokens=response.usage.input_tokens + response.usage.output_tokens,
        ),
        created_at=created_at,
        capability_calls=capability_calls_list if capability_calls_list else None,
        metadata={
            "stop_sequence": getattr(response, "stop_sequence", None),
            "tool_calls": capability_calls_metadata if capability_calls_metadata else None,
            "content": [
                {
                    "type": block.type,
                    "id": getattr(block, "id", None),
                    "name": getattr(block, "name", None),
                    "input": plain(getattr(block, "input", None)),
                }
                for block in response.content
                if block.type == "tool_use"
            ],
        },
    )


def transform_stream_chunk(chunk: Any) -> StreamChunk:
    """Transform Anthropic stream chunk to StreamChunk.

    Args:
        chunk: The Anthropic stream event

    Returns:
        StreamChunk in skye format
    """
    delta_content = ""
    finish_reason = None
    etype = getattr(chunk, "type", None)
    delta = getattr(chunk, "delta", None)
    usage = None
    if etype == "message_start":
        # The input tokens come here; the output tokens are still a first count, so only the prompt is taken.
        raw = getattr(getattr(chunk, "message", None), "usage", None)
        usage = usage_of(getattr(raw, "input_tokens", None), 0) if raw is not None else None
    elif etype == "message_delta":
        # A running count of the output tokens (the input tokens too, on newer API versions).
        raw = getattr(chunk, "usage", None)
        if raw is not None:
            usage = usage_of(
                getattr(raw, "input_tokens", None), getattr(raw, "output_tokens", None)
            )

    if etype == "content_block_delta":
        if delta is not None and hasattr(delta, "text"):
            delta_content = delta.text
    elif etype == "message_delta":
        if delta is not None and hasattr(delta, "stop_reason"):
            finish_reason = delta.stop_reason

    return StreamChunk(
        id=getattr(chunk, "message_id", ""),
        delta=delta_content,
        finish_reason=finish_reason,
        index=getattr(chunk, "index", 0),
        usage=usage,
    )
