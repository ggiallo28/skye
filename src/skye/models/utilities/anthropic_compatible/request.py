"""Building the request of the Anthropic Messages format: the messages, the system text, the tools, the structured output, the parameters (D110).

Raises: ``ValueError`` when the request has no messages, or when capabilities are given but the capabilities module is not available.
Missing: optional fields (``system``, ``top_p``, ``stop_sequences``, ``tools``, ``tool_choice``, ``output_config``) are left out when the request does not set them.
Concurrency: pure functions, safe from many threads.
"""

from collections.abc import Callable
from typing import Any

from skye.base.completion import CompleteRequest
from skye.models.utilities.anthropic_compatible.capabilities import CAPABILITIES_AVAILABLE, legacy_tools
from skye.models.utilities.structured import closed_schema, schema_of


def transform_messages(messages: list[Any]) -> tuple[str | None, list[dict[str, Any]]]:
    """Transform Skye messages to Anthropic format.

    Anthropic requires the system message to be passed separately from
    the conversation messages. Tool results are formatted as user messages
    with special content blocks.

    Args:
        messages: List of Skye message objects

    Returns:
        Tuple of (system_message, anthropic_messages) where system_message
        is a string or None, and anthropic_messages is a list of dicts
    """
    from skye.base.messages import AssistantMessage, CapabilityMessage, SystemMessage

    system = None
    anthropic_messages = []

    for msg in messages:
        if isinstance(msg, SystemMessage):
            system = msg.content
        elif isinstance(msg, CapabilityMessage):
            anthropic_messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": msg.capability_id,
                            "content": msg.content,
                        }
                    ],
                }
            )
        else:
            content: str | list[dict[str, Any]] = msg.content
            images = getattr(msg, "images", None)
            if images:
                from skye.models.utilities.multimodal import ImageHandler

                content = [
                    *(ImageHandler.to_anthropic_format(image) for image in images),
                    {"type": "text", "text": msg.content},
                ]
            if isinstance(msg, AssistantMessage) and msg.capability_calls:
                content = [
                    {
                        "type": "tool_use",
                        "id": call["id"],
                        "name": call["function"]["name"],
                        "input": call["function"]["arguments"],
                    }
                    for call in msg.capability_calls
                ]
            anthropic_messages.append({"role": msg.role, "content": content})

    return system, anthropic_messages


def transform_request(
    request: CompleteRequest,
    messages_to_anthropic: Callable[[list[Any]], tuple[str | None, list[dict[str, Any]]]],
    capabilities_to_anthropic: Callable[[list[Any]], list[dict[str, Any]]],
) -> dict[str, Any]:
    """Transform CompleteRequest to Anthropic format.

    Anthropic requires system messages to be passed separately from the
    conversation messages. The two conversions are passed in (the provider's own methods), so a
    subclass that overrides one of them is still honoured.

    Args:
        request: The skye CompleteRequest
        messages_to_anthropic: Converts the Skye messages to ``(system, messages)``
        capabilities_to_anthropic: Converts the Skye capabilities to tool definitions

    Returns:
        Dictionary in Anthropic API format
    """
    # Ensure messages are available
    if not request.messages:
        raise ValueError("messages must be provided for Anthropic provider")

    # Transform messages and extract system message using internal method
    system, anthropic_messages = messages_to_anthropic(request.messages)

    anthropic_request: dict[str, Any] = {
        "model": request.model,
        "messages": anthropic_messages,
        "temperature": request.temperature,
        "stream": request.stream,
    }

    # Add system message if present
    if system:
        anthropic_request["system"] = system

    if request.max_tokens:
        anthropic_request["max_tokens"] = request.max_tokens
    else:
        # Anthropic requires max_tokens, set a default
        anthropic_request["max_tokens"] = 4096

    if request.top_p:
        anthropic_request["top_p"] = request.top_p

    if request.stop:
        anthropic_request["stop_sequences"] = request.stop

    # Handle tool use (Anthropic's function calling)
    if request.capabilities:
        # Check if capabilities are CapabilityInterface objects or dicts
        if request.capabilities and isinstance(request.capabilities[0], dict):
            # Legacy support: capabilities are already in dict format
            anthropic_request["tools"] = legacy_tools(request.capabilities)
        elif CAPABILITIES_AVAILABLE:
            # Use internal method to convert capabilities to Anthropic format
            anthropic_request["tools"] = capabilities_to_anthropic(request.capabilities)
        else:
            # Capabilities module not available
            raise ValueError(
                "Capabilities module not installed. Install with: pip install skyeai[capabilities]"
            )

        # Handle capability choice
        if request.capability_choice:
            if request.capability_choice == "auto":
                anthropic_request["tool_choice"] = {"type": "auto"}
            elif request.capability_choice == "required":
                anthropic_request["tool_choice"] = {"type": "any"}
            elif isinstance(request.capability_choice, str):
                # Specific capability name
                anthropic_request["tool_choice"] = {
                    "type": "tool",
                    "name": request.capability_choice,
                }
            elif isinstance(request.capability_choice, dict):
                # Already formatted tool choice
                anthropic_request["tool_choice"] = request.capability_choice

    # Structured output, with or without capabilities: the native JSON output
    # (``output_config.format``). No answer is forced through a tool: ``tool_choice`` ``tool`` and
    # ``any`` return a 400 on Claude Opus 5.5, Sonnet 5.5 and Fable 5.1 (owner decision of
    # 2026-11-11). With capabilities, the model may call them and its final answer follows the schema.
    if request.response_schema:
        output_config = dict(anthropic_request.get("output_config") or {})
        output_config["format"] = {
            "type": "json_schema",
            "schema": closed_schema(schema_of(request.response_schema)),
        }
        anthropic_request["output_config"] = output_config

    # Provider-specific metadata
    if request.metadata:
        for key, value in request.metadata.items():
            if key.startswith("anthropic_"):
                anthropic_request[key[10:]] = value

    return anthropic_request
