# D81, D101
"""Prompt parts to a completion request, from the capabilities of the model (R33.9).

``prompts`` renders a prompt as ``PromptParts`` (``base``), which names no provider. This module
decides, from the model information an adapter reports (``get_model_info()``), which parts travel
in native fields and which become text:

- the system text becomes a ``SystemMessage``, which every adapter lifts into its native field
  (Anthropic ``system``, Gemini ``systemInstruction``, Bedrock Converse ``system``, an OpenAI
  system message); a model that reports ``supports_system_messages=False`` gets it in front of
  the first user message instead;
- the output schema becomes ``response_schema``, which the adapter sends natively (OpenAI
  ``response_format``, Gemini ``responseSchema``) or through one forced tool (Anthropic,
  Bedrock); a model with neither ``supports_structured_output`` nor ``supports_function_calling``
  gets the fallback text in the instructions and returns plain text.

``models`` never imports ``prompts``: the parts type comes from ``base``.

Example:
    >>> from skye.base.interfaces.prompt import OutputSchema, PromptParts
    >>> from skye.base.messages import UserMessage
    >>> parts = PromptParts(messages=(UserMessage(content="Hi"),), system="Be brief.")
    >>> request = request_from_parts(parts, model="m", info={"supports_system_messages": True})
    >>> [m.role for m in request.messages]
    ['system', 'user']
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import Any

from skye.base.completion import CompleteRequest
from skye.base.messages import SkyeMessage, SystemMessage, UserMessage
from skye.base.prompt_parts import PromptParts
from skye.models.utilities.structured import schema_instruction


def native_output(info: Mapping[str, Any]) -> bool:
    """Whether the model can be held to an output schema natively or through a forced tool."""
    return bool(info.get("supports_structured_output") or info.get("supports_function_calling"))


def request_from_parts(
    parts: PromptParts, *, model: str, info: Mapping[str, Any] | None = None, **options: Any
) -> CompleteRequest:
    """The completion request for ``parts`` on a model described by ``info``.

    Args:
        parts: The rendered prompt.
        model: The model identifier.
        info: What the adapter reports in ``get_model_info()``; an absent key counts as supported
            for the system prompt and as unsupported for the output schema.
        **options: Other request fields (``temperature``, ``max_tokens``, ``capabilities``, ...).

    Returns:
        A ``CompleteRequest``; ``response_schema`` is the ``OutputSchema`` when the model can
        follow it, otherwise ``None`` and the output instructions are in the text.
    """
    info = info or {}
    system = parts.system
    response_schema = None
    if parts.output is not None:
        if native_output(info):
            response_schema = parts.output
        else:
            instruction = parts.fallback_text or schema_instruction(parts.output)
            system = f"{system}\n\n{instruction}" if system else instruction
    messages: list[SkyeMessage] = list(parts.messages)
    if system:
        if info.get("supports_system_messages", True):
            messages.insert(0, SystemMessage(content=system))
        else:
            messages = _prefix_first_user(messages, system)
    return CompleteRequest(
        messages=messages, model=model, response_schema=response_schema, **options
    )


def _prefix_first_user(messages: list[SkyeMessage], text: str) -> list[SkyeMessage]:
    for index, message in enumerate(messages):
        if isinstance(message, UserMessage):
            messages[index] = dataclasses.replace(message, content=f"{text}\n\n{message.content}")
            return messages
    return [UserMessage(content=text), *messages]


__all__ = ["native_output", "request_from_parts"]
