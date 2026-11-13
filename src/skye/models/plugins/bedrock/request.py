# D110
"""Bedrock request: how a Skye request becomes a Converse API request (plugin ``bedrock``).

Messages (roles, images, tool use and results, merged so that roles alternate), the inference
parameters, the capabilities and the choice among them,
the structured output (native JSON output on Claude, a forced answer tool elsewhere) and the
``bedrock_*`` metadata. Module functions called by the thin
methods of ``BedrockProvider``; they import nothing of another provider.
"""

import base64
import json
from collections.abc import Callable
from typing import Any

from skye.base.completion import CompleteRequest
from skye.models.plugins.bedrock.capabilities import transform_capabilities
from skye.models.utilities.structured import (
    STRUCTURED_TOOL,
    closed_schema,
    schema_instruction,
    schema_name,
    schema_of,
)


def transform_messages(messages: list[Any]) -> list[dict[str, Any]]:
    """Transform Skye messages to Bedrock Converse API format.

    Bedrock uses a content array format where each message has a content
    array containing text or tool use/result blocks.

    Args:
        messages: List of Skye message objects

    Returns:
        List of dictionaries in Bedrock Converse API format
    """
    from skye.base.messages import AssistantMessage, CapabilityMessage, SystemMessage

    result = []
    for msg in messages:
        if isinstance(msg, SystemMessage):
            result.append({"role": "system", "content": [{"text": msg.content}]})
        elif isinstance(msg, CapabilityMessage):
            result.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "toolResult": {
                                "toolUseId": msg.capability_id,
                                "content": [{"text": msg.content}],
                            }
                        }
                    ],
                }
            )
        else:
            content: list[dict[str, Any]] = [{"text": msg.content}]
            images = getattr(msg, "images", None)
            if images:
                from skye.models.utilities.multimodal import ImageHandler

                blocks = []
                for image in images:
                    block = ImageHandler.to_bedrock_format(image)
                    source = block["image"]["source"]
                    # The REST body is JSON: bytes travel as base64 text.
                    source["bytes"] = base64.b64encode(source["bytes"]).decode("ascii")
                    blocks.append(block)
                content = [*blocks, {"text": msg.content}]
            if isinstance(msg, AssistantMessage) and msg.capability_calls:
                content = [
                    {
                        "toolUse": {
                            "toolUseId": call["id"],
                            "name": call["function"]["name"],
                            "input": call["function"]["arguments"],
                        }
                    }
                    for call in msg.capability_calls
                ]
            result.append({"role": msg.role, "content": content})
    # Converse wants the roles to alternate: consecutive user (or assistant) messages, such as
    # several capability results or the instruction of an emulated choice (D109), become one.
    merged: list[dict[str, Any]] = []
    for entry in result:
        if merged and entry["role"] != "system" and merged[-1]["role"] == entry["role"]:
            merged[-1] = {
                "role": entry["role"],
                "content": [*merged[-1]["content"], *entry["content"]],
            }
        else:
            merged.append(entry)
    return merged


def transform_request(
    request: CompleteRequest,
    *,
    native: bool,
    messages_fn: Callable[[list[Any]], list[dict[str, Any]]] = transform_messages,
    capabilities_fn: Callable[[list[Any]], list[dict[str, Any]]] = transform_capabilities,
) -> dict[str, Any]:
    """Transform CompleteRequest to Bedrock Converse API format.

    Args:
        request: The skye CompleteRequest
        native: Whether the model takes the schema natively (``outputConfig.textFormat``), decided
            by the provider
        messages_fn: What turns the messages into Converse messages (the provider's method, so an
            override still applies)
        capabilities_fn: What turns the capabilities into ``toolSpec`` entries (likewise)

    Returns:
        Dictionary in Bedrock Converse API format
    """
    # Ensure messages are available
    if not request.messages:
        raise ValueError("messages must be provided for Bedrock provider")

    messages = messages_fn(request.messages)
    # Converse takes the system prompt as a top-level field, not as a message
    system = [block for m in messages if m["role"] == "system" for block in m["content"]]
    bedrock_request: dict[str, Any] = {
        "modelId": request.model,
        "messages": [m for m in messages if m["role"] != "system"],
        "inferenceConfig": {"temperature": request.temperature},
    }

    # Claude models take the schema natively (``outputConfig.textFormat``, below). Other Converse
    # models
    # cannot force the answer tool and offer the others in one turn, so with capabilities the schema
    # travels as instructions and the final text answer is checked against it.
    if request.response_schema and request.capabilities and not native:
        system = [*system, {"text": schema_instruction(request.response_schema)}]

    if system:
        bedrock_request["system"] = system

    if request.max_tokens:
        bedrock_request["inferenceConfig"]["maxTokens"] = request.max_tokens

    if request.top_p:
        bedrock_request["inferenceConfig"]["topP"] = request.top_p

    if request.stop:
        bedrock_request["inferenceConfig"]["stopSequences"] = request.stop

    # Handle function/tool calling
    if request.capabilities:
        # Check if capabilities are CapabilityInterface objects or dicts
        if request.capabilities and isinstance(request.capabilities[0], dict):
            # Legacy support: capabilities are already in dict format
            bedrock_request["toolConfig"] = {
                "tools": [{"toolSpec": cap} for cap in request.capabilities]
            }
        else:
            # Use internal method to convert capabilities to Bedrock format
            bedrock_request["toolConfig"] = {"tools": capabilities_fn(request.capabilities)}

            # Handle capability_choice parameter
            if request.capability_choice:
                if request.capability_choice == "auto":
                    bedrock_request["toolConfig"]["toolChoice"] = {"auto": {}}
                elif request.capability_choice == "required":
                    bedrock_request["toolConfig"]["toolChoice"] = {"any": {}}
                elif isinstance(request.capability_choice, str):
                    # Specific capability name
                    bedrock_request["toolConfig"]["toolChoice"] = {
                        "tool": {"name": request.capability_choice}
                    }
                elif isinstance(request.capability_choice, dict):
                    # Already formatted capability choice
                    bedrock_request["toolConfig"]["toolChoice"] = request.capability_choice

    # Structured output on Claude: native JSON output, no forced tool (a forced ``toolChoice`` fails
    # on Claude Opus 5.5, Sonnet 5.5 and Fable 5.1; owner decision of 2026-11-11). The schema is a
    # JSON string and every object is closed, as Bedrock requires.
    if native:
        bedrock_request["outputConfig"] = {
            "textFormat": {
                "type": "json_schema",
                "structure": {
                    "jsonSchema": {
                        "schema": json.dumps(closed_schema(schema_of(request.response_schema))),
                        "name": schema_name(request.response_schema),
                    }
                },
            }
        }

    # Structured output on other Converse models: the answer is forced through one tool
    if request.response_schema and not request.capabilities and not native:
        bedrock_request["toolConfig"] = {
            "tools": [
                {
                    "toolSpec": {
                        "name": STRUCTURED_TOOL,
                        "description": "Return the answer as a "
                        f"{schema_name(request.response_schema)}.",
                        "inputSchema": {"json": schema_of(request.response_schema)},
                    }
                }
            ],
            "toolChoice": {"tool": {"name": STRUCTURED_TOOL}},
        }

    # Provider-specific metadata
    if request.metadata:
        for key, value in request.metadata.items():
            if key.startswith("bedrock_"):
                # Handle bedrock-specific parameters
                param_name = key[8:]  # Remove "bedrock_" prefix
                if param_name == "system":
                    bedrock_request["system"] = value
                elif param_name == "additionalModelRequestFields":
                    bedrock_request["additionalModelRequestFields"] = value

    return bedrock_request
