"""Google (Gemini): the JSON Schema of a reply in the subset of ``responseSchema`` (D110).

Raises: nothing; a schema that needs more than the subset gives ``None``.
Missing: not applicable.
Concurrency: stateless.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class _NotSupportedError(Exception):
    pass


_GEMINI_KEYS = {
    "type",
    "format",
    "description",
    "nullable",
    "enum",
    "items",
    "properties",
    "required",
    "minItems",
    "maxItems",
    "minimum",
    "maximum",
    "propertyOrdering",
    "anyOf",
    "title",
}


def gemini_schema(schema: Mapping[str, Any]) -> dict[str, Any] | None:
    """The schema in Gemini's ``responseSchema`` subset, or ``None`` when it needs more.

    Types are upper case (``STRING``, ``OBJECT``), ``["string", "null"]`` becomes ``nullable``,
    and ``additionalProperties`` and ``$schema`` are dropped (Gemini rejects them). A ``$ref``,
    ``$defs`` or another keyword outside the subset gives ``None``, and the caller asks for JSON
    with the schema in the instructions instead.
    """

    def convert(node: Any) -> Any:
        if not isinstance(node, Mapping):
            raise _NotSupportedError
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key in ("additionalProperties", "$schema"):
                continue
            if key not in _GEMINI_KEYS:
                raise _NotSupportedError
            if key == "type":
                types = [value] if isinstance(value, str) else list(value)
                if "null" in types:
                    out["nullable"] = True
                    types.remove("null")
                if len(types) != 1:
                    raise _NotSupportedError
                out["type"] = types[0].upper()
            elif key == "properties":
                out["properties"] = {name: convert(sub) for name, sub in value.items()}
            elif key == "items":
                out["items"] = convert(value)
            elif key == "anyOf":
                options = [sub for sub in value if sub.get("type") != "null"]
                if len(options) < len(value):
                    out["nullable"] = True
                if len(options) == 1:
                    out.update(convert(options[0]))
                else:
                    out["anyOf"] = [convert(sub) for sub in options]
            else:
                out[key] = value
        return out

    try:
        converted: dict[str, Any] = convert(schema)
    except (_NotSupportedError, AttributeError, TypeError):
        return None
    return converted
