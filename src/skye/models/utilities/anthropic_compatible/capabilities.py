"""Capabilities for the Anthropic Messages format: the tool definitions sent, the tool calls read back, the results formatted (D110).

Raises: nothing of its own; ``extract_capability_calls`` reads blocks the endpoint returned and does not validate them.
Missing: ``extract_capability_calls`` returns ``None`` when the response has no tool call (or when the capability calls are unavailable).
Concurrency: pure functions, safe from many threads.
"""

import json
from typing import Any

from skye.models.utilities import rest
from skye.models.utilities.structured import STRUCTURED_TOOL

# Import CapabilityCall for capability call extraction
try:
    from skye.base.completion import CapabilityCall

    CAPABILITIES_AVAILABLE = True
except ImportError:
    CAPABILITIES_AVAILABLE = False


def plain(value: Any) -> Any:
    """Unwrap a JsonObject (tool ``input``) back to a plain dict."""
    return value.to_dict() if isinstance(value, rest.JsonObject) else value


def legacy_tools(capabilities: list[Any]) -> list[dict[str, Any]]:
    """Tool definitions from capabilities already given as OpenAI-style ``{"type": "function", ...}`` dicts (legacy support)."""
    anthropic_tools = []
    for cap in capabilities:
        if cap.get("type") == "function":
            func = cap["function"]
            anthropic_tools.append(
                {
                    "name": func["name"],
                    "description": func.get("description", ""),
                    "input_schema": func.get("parameters", {}),
                }
            )
    return anthropic_tools


def transform_capabilities(capabilities: list[Any]) -> list[dict[str, Any]]:
    """Transform Skye capabilities to Anthropic tool use format.

    Anthropic uses a flat structure with "name", "description", and
    "input_schema" fields.

    Args:
        capabilities: List of CapabilityInterface objects or dicts

    Returns:
        List of tool definitions in Anthropic format
    """
    tools = []
    for capability in capabilities:
        # Handle both CapabilityInterface objects and dict format
        if isinstance(capability, dict):
            # Check if already in Anthropic format
            if "input_schema" in capability:
                tools.append(capability)
            else:
                # Convert from OpenAI format to Anthropic format
                func = capability.get("function", {})
                tool = {
                    "name": func.get("name", ""),
                    "description": func.get("description", ""),
                    "input_schema": func.get(
                        "parameters",
                        {
                            "type": "object",
                            "properties": {},
                        },
                    ),
                }
                tools.append(tool)
        else:
            # CapabilityInterface object, convert to Anthropic format
            schema = capability.get_schema()
            tool = {
                "name": schema.name,
                "description": schema.description,
                "input_schema": schema.parameters
                or {
                    "type": "object",
                    "properties": {},
                },
            }
            tools.append(tool)
    return tools


def extract_capability_calls(response: Any, unwrap: Any = plain) -> list[Any] | None:
    """Extract capability calls from Anthropic response.

    Parses tool use blocks from the Anthropic response format and converts them
    to Skye CapabilityCall objects.

    Args:
        response: Anthropic response object
        unwrap: Turns a tool ``input`` into a plain dict (the provider's ``_plain``)

    Returns:
        List of CapabilityCall objects, or None if no capability calls
    """
    if not CAPABILITIES_AVAILABLE:
        return None

    capability_calls = []
    for content_block in response.content:
        if content_block.type == "tool_use" and content_block.name != STRUCTURED_TOOL:
            capability_calls.append(
                CapabilityCall(
                    id=content_block.id,
                    name=content_block.name,
                    arguments=unwrap(content_block.input),
                )
            )

    return capability_calls if capability_calls else None


def format_capability_results(results: list[Any]) -> list[dict[str, Any]]:
    """Format capability results for Anthropic.

    Anthropic expects tool results in this format:
    {
        "type": "tool_result",
        "tool_use_id": "toolu_123",
        "content": "{\"result\": \"value\"}"
    }

    Args:
        results: List of CapabilityResult objects

    Returns:
        List of formatted result dictionaries in Anthropic format
    """
    formatted = []
    for result in results:
        # Convert result to JSON string
        if result.error:
            content = json.dumps({"error": result.error})
        elif isinstance(result.result, str):
            content = result.result
        else:
            content = json.dumps(result.result)

        formatted.append(
            {
                "type": "tool_result",
                "tool_use_id": result.capability_call_id,
                "content": content,
            }
        )

    return formatted
