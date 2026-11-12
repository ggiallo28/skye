"""Google (Gemini): capabilities out and back (D110).

Skye capabilities become ``functionDeclarations``, the ``functionCall`` parts of a response become ``CapabilityCall`` objects, and the results are
formatted as ``functionResponse``. Plain functions, so the provider class stays thin; ``GoogleProvider`` keeps the same methods and calls these.
"""

import json
from typing import Any

from skye.base.completion import CapabilityCall
from skye.models.utilities.rest import JsonObject, wrap


def as_args(arguments: Any) -> dict[str, Any]:
    """The arguments of a call as a dict: a JSON string is decoded, anything that is not an object becomes ``{}``."""
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments) if arguments else {}
        except json.JSONDecodeError:
            arguments = {}
    return arguments if isinstance(arguments, dict) else {}


def transform_capabilities(capabilities: list[Any]) -> list[dict[str, Any]]:
    """Transform Skye capabilities to Google Gemini format.

    Google uses a format with "name", "description", and "parameters"
    fields. The parameters field is the JSON Schema for parameters.

    Args:
        capabilities: List of CapabilityInterface objects or dicts

    Returns:
        List of tool definitions in Google format
    """
    tools = []
    for capability in capabilities:
        # Handle both CapabilityInterface objects and dict format
        if isinstance(capability, dict):
            # Check if already in Google format
            if "parameters" in capability and "function" not in capability:
                tools.append(capability)
            else:
                # Convert from OpenAI format to Google format
                func = capability.get("function", {})
                tool = {
                    "name": func.get("name", ""),
                    "description": func.get("description", ""),
                    "parameters": func.get(
                        "parameters",
                        {
                            "type": "object",
                            "properties": {},
                        },
                    ),
                }
                tools.append(tool)
        else:
            # CapabilityInterface object, convert to Google format
            schema = capability.get_schema()
            tool = {
                "name": schema.name,
                "description": schema.description,
                "parameters": schema.parameters
                or {
                    "type": "object",
                    "properties": {},
                },
            }
            tools.append(tool)
    return tools


def extract_capability_calls(response: Any) -> list[Any] | None:
    """Extract ``functionCall`` parts from a ``generateContent`` response.

    Returns:
        List of CapabilityCall objects, or None if the response has none.
    """
    calls: list[CapabilityCall] = []
    candidates = wrap(response).get("candidates") or []
    if not candidates:
        return None
    parts = (candidates[0].get("content") or JsonObject({})).get("parts") or []
    for idx, part in enumerate(parts):
        fc = part.get("functionCall")
        if fc is not None:
            args = fc.get("args")
            calls.append(
                CapabilityCall(
                    id=f"google_call_{idx}",  # Google does not provide call ids
                    name=fc.get("name", ""),
                    arguments=args.to_dict() if isinstance(args, JsonObject) else {},
                )
            )
    return calls or None


def format_capability_results(results: list[Any]) -> list[dict[str, Any]]:
    """Format capability results for Google.

    Google expects tool results in this format:
    {
        "functionResponse": {
            "name": "get_weather",
            "response": {"result": "value"}
        }
    }

    Args:
        results: List of CapabilityResult objects

    Returns:
        List of formatted result dictionaries in Google format
    """
    formatted = []
    for result in results:
        # Convert result to appropriate format
        if result.error:
            response_data = {"error": result.error}
        elif isinstance(result.result, dict):
            response_data = result.result
        elif isinstance(result.result, str):
            try:
                response_data = json.loads(result.result)
            except json.JSONDecodeError:
                response_data = {"result": result.result}
        else:
            response_data = {"result": result.result}

        formatted.append(
            {
                "functionResponse": {
                    "name": result.name,
                    "response": response_data,
                }
            }
        )

    return formatted
