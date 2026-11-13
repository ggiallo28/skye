# Requirement 33.9, decisions D81, D101
"""Prompt parts: a rendered prompt with no provider in it, between ``prompts`` and ``models``.

``prompts`` produces :class:`PromptParts`; the ``models`` adapters read it and choose native fields
or text from the model capabilities. The type lives in
``base`` so neither component imports the other; ``skye.base.interfaces`` re-exports it next to
the prompt Ports. Standard library only.

Raises: nothing; the types are plain frozen dataclasses and check nothing at construction.
Missing: ``system``, ``output`` and ``fallback_text`` are ``None`` when absent; ``messages`` is
an empty tuple.
Concurrency: the instances are frozen and safe to share between threads and tasks.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from skye.base.messages import SkyeMessage


# decisions D81, D101
@dataclass(frozen=True)
class OutputSchema:
    """The shape a rendered prompt asks the model to answer in.

    Pass it as ``response_schema`` of a completion request, like a dataclass: the adapter uses the
    provider's native mode (OpenAI ``response_format``, Gemini ``responseSchema``) or forces one
    tool (Anthropic, Bedrock), and the reply comes back as a ``dict`` in ``structured_output``.

    Attributes:
        name: A short name of the answer (letters, digits, ``_`` and ``-``), sent to the
            providers that ask for one.
        schema: The JSON Schema of the answer, an object schema.
        strict: Ask for strict adherence where the provider has a strict mode and the schema
            allows it.

    Example:
        >>> OutputSchema("person", {"type": "object"}).name
        'person'
    """

    name: str
    schema: Mapping[str, Any]
    strict: bool = True


# Requirement 33.9, decisions D81, D101
@dataclass(frozen=True)
class PromptParts:
    """A rendered prompt as provider-agnostic parts.

    The renderer of ``prompts`` returns it; ``models`` turns it into a native request (the system
    prompt and the output schema in the provider's own fields) or, when the model lacks a native
    field, into text. Neither side imports the other: this type is the contract between them.

    Attributes:
        messages: The conversation, in order; it never holds the system text, which is
            ``system``.
        system: The system instructions, or ``None``.
        output: The schema of the answer, or ``None`` for free text.
        fallback_text: The output instructions in words, used when the model can follow neither
            a native schema nor a forced tool; ``None`` lets the adapter write its own sentence
            from ``output``.

    Example:
        >>> from skye.base.messages import UserMessage
        >>> parts = PromptParts(messages=(UserMessage(content="Hi"),), system="Be brief.")
        >>> parts.system, len(parts.messages)
        ('Be brief.', 1)
    """

    messages: tuple[SkyeMessage, ...] = field(default_factory=tuple)
    system: str | None = None
    output: OutputSchema | None = None
    fallback_text: str | None = None


__all__ = ["OutputSchema", "PromptParts"]
