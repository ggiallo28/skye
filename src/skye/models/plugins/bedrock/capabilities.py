"""Bedrock capabilities: Skye capabilities out to the Converse ``toolSpec`` format, the tool calls read back, and the results formatted (plugin ``bedrock``, D110).

Module functions called by the thin methods of ``BedrockProvider``; they import nothing of another provider.
"""

import json
from typing import Any

from skye.base.completion import CapabilityCall
from skye.models.utilities import rest
from skye.models.utilities.structured import STRUCTURED_TOOL


def transform_capabilities(capabilities: list[Any]) -> list[dict[str, Any]]:
    """Transform Skye capabilities to Bedrock Converse API format.

    Bedrock uses a nested structure with "toolSpec" containing the tool
    definition. The inputSchema is the JSON Schema for parameters.

    Args:
        capabilities: List of CapabilityInterface objects or dicts

    Returns:
        List of tool definitions in Bedrock format
    """
    tools = []
    for capability in capabilities:
        # Handle both CapabilityInterface objects and dict format
        if isinstance(capability, dict):
            # Check if already in Bedrock format
            if "toolSpec" in capability:
                tools.append(capability)
            else:
                # Convert from OpenAI format to Bedrock format
                func = capability.get("function", {})
                tool = {
                    "toolSpec": {
                        "name": func.get("name", ""),
                        "description": func.get("description", ""),
                        "inputSchema": {
                            "json": func.get(
                                "parameters",
                                {
                                    "type": "object",
                                    "properties": {},
                                },
                            )
                        },
                    }
                }
                tools.append(tool)
        else:
            # CapabilityInterface object, convert to Bedrock format
            schema = capability.get_schema()
            tool = {
                "toolSpec": {
                    "name": schema.name,
                    "description": schema.description,
                    "inputSchema": {
                        "json": schema.parameters
                        or {
                            "type": "object",
                            "properties": {},
                        }
                    },
                }
            }
            tools.append(tool)
    return tools


def extract_capability_calls(response: Any) -> list[Any] | None:
    """Extract capability calls from Bedrock response.

    Parses tool use blocks from the Bedrock response format and converts them
    to Skye CapabilityCall objects.

    Args:
        response: Bedrock response dictionary

    Returns:
        List of CapabilityCall objects, or None if no capability calls
    """
    if isinstance(response, rest.JsonObject):
        response = response.to_dict()
    output = response.get("output", {})
    message = output.get("message", {})

    capability_calls = []
    for content_block in message.get("content", []):
        if "toolUse" in content_block and content_block["toolUse"]["name"] != STRUCTURED_TOOL:
            tool_use = content_block["toolUse"]

            capability_calls.append(
                CapabilityCall(
                    id=tool_use["toolUseId"], name=tool_use["name"], arguments=tool_use["input"]
                )
            )

    return capability_calls if capability_calls else None


def format_capability_results(results: list[Any]) -> list[dict[str, Any]]:
    """Format capability results for Bedrock.

    Bedrock expects tool results in this format:
    {
        "toolResult": {
            "toolUseId": "tooluse_123",
            "content": [
                {
                    "json": {"result": "value"}
                }
            ]
        }
    }

    Args:
        results: List of CapabilityResult objects

    Returns:
        List of formatted result dictionaries in Bedrock format
    """
    formatted = []
    for result in results:
        # Convert result to appropriate format
        if result.error:
            result_data = {"error": result.error}
        elif isinstance(result.result, dict):
            result_data = result.result
        elif isinstance(result.result, str):
            try:
                result_data = json.loads(result.result)
            except json.JSONDecodeError:
                result_data = {"result": result.result}
        else:
            result_data = {"result": result.result}

        formatted.append(
            {
                "toolResult": {
                    "toolUseId": result.capability_call_id,
                    "content": [{"json": result_data}],
                }
            }
        )

    return formatted
