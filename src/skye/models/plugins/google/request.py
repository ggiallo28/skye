# D110
"""Google (Gemini): how the request is built.

Skye messages become Gemini ``contents`` (parts), and a ``CompleteRequest`` becomes the Vertex AI
REST body: system instruction, generation config,
native ``responseSchema`` or JSON mode, tools and tool config, safety settings, grounding and the
``google_<field>`` passthrough. Plain functions, so the
provider class stays thin; ``GoogleProvider`` keeps the same methods and calls these.
"""

from collections.abc import Callable
from typing import Any

from skye.base.completion import CompleteRequest
from skye.models.plugins.google.capabilities import (
    as_args,
)
from skye.models.plugins.google.capabilities import (
    transform_capabilities as default_transform_capabilities,
)
from skye.models.plugins.google.schema import gemini_schema
from skye.models.utilities.structured import schema_instruction, schema_of


def transform_messages(messages: list[Any]) -> list[dict[str, Any]]:
    """Transform Skye messages to Google (Gemini) format.

    Google uses a parts-based format where content is broken into parts.
    System messages are kept here as ``role: system`` and moved to
    ``systemInstruction`` by :func:`transform_request`.

    Args:
        messages: List of Skye message objects

    Returns:
        List of dictionaries in Google format
    """
    from skye.base.messages import AssistantMessage, CapabilityMessage, SystemMessage

    result = []
    for msg in messages:
        if isinstance(msg, SystemMessage):
            result.append({"role": "system", "parts": [{"text": msg.content}]})
        elif isinstance(msg, CapabilityMessage):
            result.append(
                {
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": msg.capability_name,
                                "response": {"content": msg.content},
                            }
                        }
                    ],
                }
            )
        else:
            # Map assistant to model for Google
            role = "model" if msg.role == "assistant" else msg.role
            parts: list[dict[str, Any]] = [{"text": msg.content}]
            images = getattr(msg, "images", None)
            if images:
                from skye.models.utilities.multimodal import ImageHandler

                parts = [*(ImageHandler.to_google_format(image) for image in images), *parts]

            if isinstance(msg, AssistantMessage) and msg.capability_calls:
                parts = [
                    {
                        "functionCall": {
                            "name": call["function"]["name"],
                            "args": as_args(call["function"]["arguments"]),
                        }
                    }
                    for call in msg.capability_calls
                ]

            result.append({"role": role, "parts": parts})
    return result


def transform_request(
    request: CompleteRequest,
    messages_transformer: Callable[[list[Any]], list[dict[str, Any]]] = transform_messages,
    capabilities_transformer: Callable[
        [list[Any]], list[dict[str, Any]]
    ] = default_transform_capabilities,
) -> dict[str, Any]:
    """Transform CompleteRequest to the Vertex AI REST body.

    The returned dict carries ``model`` (consumed by the provider's call, not sent) plus
    ``contents``, ``systemInstruction``, ``generationConfig``, ``tools``, ``toolConfig``
    and ``safetySettings``. The two transformers are the provider's own methods, so a subclass that
    overrides one is still used.
    """
    if not request.messages:
        raise ValueError("messages must be provided for Google provider")

    transformed = messages_transformer(request.messages)
    system_parts = [p for m in transformed if m["role"] == "system" for p in m["parts"]]
    contents = [m for m in transformed if m["role"] != "system"]

    generation_config: dict[str, Any] = {"temperature": request.temperature}
    google_request: dict[str, Any] = {
        "model": request.model,
        "contents": contents,
        "generationConfig": generation_config,
    }
    if request.response_schema:
        # Native responseSchema when the schema fits Gemini's OpenAPI subset; else JSON mode plus
        # the schema in the instructions
        generation_config["responseMimeType"] = "application/json"
        native = gemini_schema(schema_of(request.response_schema))
        if native is not None:
            generation_config["responseSchema"] = native
        else:
            system_parts = [*system_parts, {"text": schema_instruction(request.response_schema)}]
    if system_parts:
        google_request["systemInstruction"] = {"parts": system_parts}

    if request.max_tokens:
        generation_config["maxOutputTokens"] = request.max_tokens
    if request.top_p:
        generation_config["topP"] = request.top_p
    if request.stop:
        generation_config["stopSequences"] = request.stop

    if request.metadata and "safety_settings" in request.metadata:
        google_request["safetySettings"] = request.metadata["safety_settings"]

    tools: list[dict[str, Any]] = []
    if request.capabilities:
        tools.append({"functionDeclarations": capabilities_transformer(request.capabilities)})
        choice = request.capability_choice
        if choice == "required":
            google_request["toolConfig"] = {"functionCallingConfig": {"mode": "ANY"}}
        elif choice == "auto":
            google_request["toolConfig"] = {"functionCallingConfig": {"mode": "AUTO"}}
        elif choice and choice != "none":
            google_request["toolConfig"] = {
                "functionCallingConfig": {"mode": "ANY", "allowedFunctionNames": [choice]}
            }
        elif choice == "none":
            google_request["toolConfig"] = {"functionCallingConfig": {"mode": "NONE"}}

    # Grounding: a REST tool entry (e.g. {"googleSearchRetrieval": {}})
    if request.metadata and isinstance(request.metadata.get("grounding"), dict):
        tools.append(request.metadata["grounding"])
    if tools:
        google_request["tools"] = tools

    # Provider-specific passthrough: google_<restField>
    if request.metadata:
        for key, value in request.metadata.items():
            if key.startswith("google_"):
                google_request[key[7:]] = value

    return google_request
