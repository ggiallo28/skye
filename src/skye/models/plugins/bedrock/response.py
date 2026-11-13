# D110
"""Bedrock response: how a Converse response and a stream event become a Skye response and chunk
(plugin ``bedrock``).

Text and tool-use blocks, the structured answer returned through its tool, the token usage, the stop
reason mapped to a finish reason, and the
usage reported by the last stream event. Module functions called by the thin methods of
``BedrockProvider``; they import nothing of another provider.
"""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from skye.base.completion import CompleteResponse, StreamChunk, TokenUsage
from skye.models.cost import usage_of
from skye.models.plugins.bedrock.capabilities import extract_capability_calls
from skye.models.utilities import rest
from skye.models.utilities.structured import STRUCTURED_TOOL


def transform_response(
    response: Any,
    *,
    extract_calls: Callable[[Any], list[Any] | None] = extract_capability_calls,
) -> CompleteResponse:
    """Transform Bedrock response to CompleteResponse.

    Args:
        response: The Bedrock response object
        extract_calls: What reads the capability calls (the provider's method, so an override still
            applies)

    Returns:
        CompleteResponse in skye format
    """
    if isinstance(response, rest.JsonObject):
        response = response.to_dict()
    output = response["output"]
    message = output["message"]

    # Extract content from message
    content = ""
    tool_calls_metadata = []

    for content_block in message.get("content", []):
        if "text" in content_block:
            content += content_block["text"]
        elif "toolUse" in content_block and content_block["toolUse"]["name"] == STRUCTURED_TOOL:
            # The structured answer: its input is the JSON the declared schema describes
            content += json.dumps(content_block["toolUse"]["input"])
        elif "toolUse" in content_block:
            # Store in metadata for compatibility
            tool_use = content_block["toolUse"]
            tool_calls_metadata.append(
                {
                    "id": tool_use["toolUseId"],
                    "type": "function",
                    "function": {"name": tool_use["name"], "arguments": tool_use["input"]},
                }
            )

    # Extract capability calls using internal method
    tool_calls_list = extract_calls(response)

    # Extract usage information
    usage_info = response.get("usage", {})
    usage = TokenUsage(
        prompt_tokens=usage_info.get("inputTokens", 0),
        completion_tokens=usage_info.get("outputTokens", 0),
        total_tokens=usage_info.get("totalTokens", 0),
    )

    # Extract stop reason
    stop_reason = response.get("stopReason", "stop")
    finish_reason_map = {
        "end_turn": "stop",
        "tool_use": "tool_calls",
        "max_tokens": "length",
        "stop_sequence": "stop",
        "content_filtered": "content_filter",
    }
    finish_reason = finish_reason_map.get(stop_reason, stop_reason)

    return CompleteResponse(
        id=response.get("ResponseMetadata", {}).get("RequestId", ""),
        model=response.get("ResponseMetadata", {})
        .get("HTTPHeaders", {})
        .get("x-amzn-bedrock-model-id", ""),
        provider="bedrock",
        content=content,
        structured_output=None,  # Bedrock doesn't have native structured output
        role="assistant",
        finish_reason=finish_reason,
        usage=usage,
        capability_calls=tool_calls_list if tool_calls_list else None,
        created_at=datetime.now(tz=UTC),
        metadata={
            "stop_reason": stop_reason,
            "tool_calls": tool_calls_metadata if tool_calls_metadata else None,
            "metrics": response.get("metrics", {}),
        },
    )


def transform_stream_chunk(chunk: Any) -> StreamChunk:
    """Transform Bedrock stream chunk to StreamChunk.

    Args:
        chunk: The Bedrock stream chunk

    Returns:
        StreamChunk in skye format
    """
    if isinstance(chunk, rest.JsonObject):
        chunk = chunk.to_dict()
    # Bedrock streaming returns different event types
    delta = ""
    finish_reason = None

    if "contentBlockDelta" in chunk:
        delta_content = chunk["contentBlockDelta"].get("delta", {})
        if "text" in delta_content:
            delta = delta_content["text"]

    if "messageStop" in chunk:
        stop_reason = chunk["messageStop"].get("stopReason", "stop")
        finish_reason_map = {
            "end_turn": "stop",
            "tool_use": "tool_calls",
            "max_tokens": "length",
            "stop_sequence": "stop",
            "content_filtered": "content_filter",
        }
        finish_reason = finish_reason_map.get(stop_reason, stop_reason)

    # The last event, "metadata", reports the tokens of the whole call.
    reported = (chunk.get("metadata") or {}).get("usage") or {}
    usage = usage_of(
        reported.get("inputTokens"), reported.get("outputTokens"), reported.get("totalTokens")
    )

    return StreamChunk(
        id="",  # Bedrock streaming doesn't provide chunk IDs
        delta=delta,
        finish_reason=finish_reason,
        index=0,
        usage=usage,
    )
