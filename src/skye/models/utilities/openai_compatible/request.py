"""Building the chat-completions request: the messages, the structured output, the parameters, the capability choice and the provider metadata."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from skye.base.completion import CompleteRequest
from skye.models.utilities.structured import schema_name, schema_of, strict_schema, wants_strict

if TYPE_CHECKING:
    from skye.models.utilities.openai_compatible.provider import OpenAICompatibleProvider


def transform_messages(messages: list[Any]) -> list[dict[str, Any]]:
    """Transform Skye messages to OpenAI format.

    OpenAI uses a simple role-content format with capability calls as a separate field.
    System messages are included in the messages array.

    Args:
        messages: List of Skye message objects

    Returns:
        List of dictionaries in OpenAI format
    """
    from skye.base.messages import AssistantMessage, CapabilityMessage

    result = []
    for msg in messages:
        if isinstance(msg, CapabilityMessage):
            result.append(
                {
                    "role": "tool",
                    "tool_call_id": msg.capability_id,
                    "name": msg.capability_name,
                    "content": msg.content,
                }
            )
        else:
            openai_msg: dict[str, Any] = {"role": msg.role, "content": msg.content}
            images = getattr(msg, "images", None)
            if images:
                from skye.models.utilities.multimodal import ImageHandler

                openai_msg["content"] = [
                    {"type": "text", "text": msg.content},
                    *(ImageHandler.to_openai_format(image) for image in images),
                ]
            if isinstance(msg, AssistantMessage) and msg.capability_calls:
                openai_msg["tool_calls"] = msg.capability_calls
            result.append(openai_msg)
    return result


def transform_request(
    provider: OpenAICompatibleProvider, request: CompleteRequest
) -> dict[str, Any]:
    """Transform CompleteRequest to OpenAI format.

    ``provider`` supplies the model name, the message and capability transforms (a subclass may override them) and the metadata prefix.

    Args:
        provider: The provider that builds the request
        request: The skye CompleteRequest

    Returns:
        Dictionary in OpenAI API format
    """
    # Ensure messages are available
    if not request.messages:
        raise ValueError("messages must be provided for OpenAI provider")

    openai_request: dict[str, Any] = {
        "model": provider._model_name(request),
        "messages": provider._transform_messages(request.messages),
        "temperature": request.temperature,
        "stream": request.stream,
    }

    if request.max_tokens:
        openai_request["max_tokens"] = request.max_tokens

    if request.top_p:
        openai_request["top_p"] = request.top_p

    if request.stop:
        openai_request["stop"] = request.stop

    # Handle structured outputs
    if request.response_schema:
        schema = schema_of(request.response_schema)
        strict = strict_schema(schema) if wants_strict(request.response_schema) else None
        openai_request["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name(request.response_schema),
                "schema": strict or schema,
                "strict": strict is not None,
            },
        }
    elif request.response_format:
        openai_request["response_format"] = request.response_format

    # Handle capabilities/tool calling
    if request.capabilities:
        # Convert capabilities to OpenAI format using internal method
        openai_request["tools"] = provider._transform_capabilities(request.capabilities)

        # Handle capability_choice parameter
        if request.capability_choice:
            if request.capability_choice in ["auto", "required"]:
                # Standard values
                openai_request["tool_choice"] = request.capability_choice
            else:
                # Specific capability name - OpenAI expects {"type": "function", "function": {"name": "capability_name"}}
                openai_request["tool_choice"] = {
                    "type": "function",
                    "function": {"name": request.capability_choice},
                }

    # Provider-specific metadata
    if request.metadata:
        for key, value in request.metadata.items():
            if key.startswith(provider.metadata_prefix):
                openai_request[key[len(provider.metadata_prefix) :]] = value

    return openai_request
