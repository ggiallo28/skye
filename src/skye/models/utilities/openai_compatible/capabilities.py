"""Capabilities in the OpenAI wire format: the tool definitions out, the requested calls back and the results formatted for the next turn."""

from typing import Any


def transform_capabilities(capabilities: list[Any]) -> list[dict[str, Any]]:
    """Transform Skye capabilities to OpenAI function calling format.

    OpenAI uses a nested structure with "type": "function" and a "function"
    object containing the tool definition.

    Args:
        capabilities: List of CapabilityInterface objects or dicts

    Returns:
        List of tool definitions in OpenAI format
    """
    tools = []
    for capability in capabilities:
        # Handle both CapabilityInterface objects and dict format
        if isinstance(capability, dict):
            # Already in dict format, pass through
            tools.append(capability)
        else:
            # CapabilityInterface object, convert to OpenAI format
            schema = capability.get_schema()
            tool = {
                "type": "function",
                "function": {
                    "name": schema.name,
                    "description": schema.description,
                    "parameters": schema.parameters
                    or {
                        "type": "object",
                        "properties": {},
                    },
                },
            }
            tools.append(tool)
    return tools


def extract_capability_calls(response: Any) -> list[Any] | None:
    """Extract capability calls from OpenAI response.

    Parses capability calls from the OpenAI response format and converts them
    to Skye CapabilityCall objects.

    Args:
        response: OpenAI response object

    Returns:
        List of CapabilityCall objects, or None if no capability calls
    """
    choice = response.choices[0]
    message = choice.message

    if not hasattr(message, "tool_calls") or not message.tool_calls:
        return None

    import json

    from skye.base.completion import CapabilityCall

    capability_calls = []
    for tc in message.tool_calls:
        # Parse arguments JSON string
        try:
            arguments = json.loads(tc.function.arguments)
        except json.JSONDecodeError:
            # If parsing fails, use empty dict
            arguments = {}

        capability_calls.append(
            CapabilityCall(id=tc.id, name=tc.function.name, arguments=arguments)
        )

    return capability_calls


def format_capability_results(results: list[Any]) -> list[dict[str, Any]]:
    """Format capability results for OpenAI.

    OpenAI expects tool results in this format:
    {
        "tool_call_id": "call_123",
        "role": "tool",
        "content": "{\"result\": \"value\"}"
    }

    Args:
        results: List of CapabilityResult objects

    Returns:
        List of formatted result dictionaries in OpenAI format
    """
    import json

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
                "tool_call_id": result.capability_call_id,
                "role": "tool",
                "content": content,
            }
        )

    return formatted
