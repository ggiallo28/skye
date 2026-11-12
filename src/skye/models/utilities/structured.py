"""Structured output: the schema a model is asked to follow, and the check of its reply (Requirement 27, D24).

``response_schema`` is a dataclass (the standard, ``@validated`` or plain ``@dataclass``). A class with
``model_json_schema`` and ``model_validate_json`` (a user's pydantic model) is accepted too, without the library importing pydantic.
An ``OutputSchema`` of ``base`` (a JSON Schema from rendered prompt parts, D101) is accepted too;
its reply is a ``dict``, checked against the whole schema (``schema_check``).
A reply that does not conform raises ``ValidationError`` naming the field.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping
from typing import Any

from skye.base.exceptions import ValidationError
from skye.base.prompt_parts import OutputSchema
from skye.base.validated import from_mapping, json_schema, validate_instance
from skye.models.utilities.schema_check import check_json


STRUCTURED_TOOL = "skye_structured_output"
"""Name of the tool that carries a structured answer on providers without a native mode (Requirement 27.1: function calling)."""


def schema_instruction(cls: Any) -> str:
    """A sentence that asks for a JSON reply following the schema of ``cls`` (for providers with only a JSON mode)."""
    return "Reply only with a JSON object that follows this JSON Schema: " + json.dumps(schema_of(cls), separators=(",", ":"))


def schema_name(cls: Any) -> str:
    """The name sent to providers that ask for one: the ``OutputSchema`` name or the class name."""
    if isinstance(cls, OutputSchema):
        return cls.name
    return str(getattr(cls, "__name__", "answer"))


def wants_strict(cls: Any) -> bool:
    """Whether strict adherence is asked: always for a class, as set for an ``OutputSchema``."""
    return cls.strict if isinstance(cls, OutputSchema) else True


def schema_of(cls: Any) -> dict[str, Any]:
    """The JSON Schema of a declared output.

    An ``OutputSchema``, a dataclass, or a class with ``model_json_schema``.
    """
    if isinstance(cls, OutputSchema):
        # A deep, plain copy: the caller's mapping is never changed
        copied: dict[str, Any] = json.loads(json.dumps(cls.schema))
        return copied
    if hasattr(cls, "model_json_schema"):
        schema: dict[str, Any] = cls.model_json_schema()
        return schema
    if isinstance(cls, type) and dataclasses.is_dataclass(cls):
        return json_schema(cls)
    raise ValidationError(
        f"response_schema must be a dataclass, got {cls!r}", field="response_schema", value=cls
    )


def strict_schema(schema: dict[str, Any]) -> dict[str, Any] | None:
    """The schema in the form a provider's strict mode accepts, or ``None`` when it cannot be used strictly.

    Strict mode needs every object to list all its properties as required and to forbid additional ones. Only a schema that
    already meets the first condition is returned (with the second added); otherwise the provider is asked in non-strict mode.
    """
    def convert(node: Any) -> Any:
        if isinstance(node, dict):
            out = {key: convert(value) for key, value in node.items()}
            if "properties" in out:
                if set(out.get("required", [])) != set(out["properties"]):
                    raise _NotStrict
                out["additionalProperties"] = False
            return out
        if isinstance(node, list):
            return [convert(item) for item in node]
        return node

    try:
        converted: dict[str, Any] = convert(schema)
    except _NotStrict:
        return None
    return converted


#: Keywords a native JSON-output mode may reject (numeric and length bounds); the reply is still checked against them here.
_LOOSE_KEYWORDS = frozenset({"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "minLength", "maxLength"})


def closed_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    """The schema as a JSON-output mode with closed objects wants it (Anthropic ``output_config.format``).

    Every object with ``properties`` gets ``additionalProperties: false`` unless it says otherwise, and the numeric and
    length bounds are left out (the provider may reject them); :func:`parse_structured` still checks the reply against
    the full schema.
    """
    def convert(node: Any) -> Any:
        if not isinstance(node, Mapping):
            return node
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key in _LOOSE_KEYWORDS:
                continue
            if key in ("properties", "$defs", "definitions", "patternProperties") and isinstance(value, Mapping):
                out[key] = {name: convert(sub) for name, sub in value.items()}
            elif key in ("anyOf", "allOf", "oneOf", "prefixItems") and isinstance(value, list):
                out[key] = [convert(sub) for sub in value]
            elif key in ("items", "additionalProperties", "not"):
                out[key] = [convert(sub) for sub in value] if isinstance(value, list) else convert(value)
            else:
                out[key] = value
        if ("properties" in out or out.get("type") == "object") and "additionalProperties" not in out:
            out["additionalProperties"] = False
        return out

    converted: dict[str, Any] = convert(schema)
    return converted


class _NotStrict(Exception):
    pass


def parse_structured(cls: Any, text: str) -> Any:
    """Read the JSON ``text`` of a reply as ``cls``; raises ``ValidationError`` naming the field when it does not conform."""
    if isinstance(cls, OutputSchema):
        return _parse_json_object(cls, text)
    name = getattr(cls, "__name__", str(cls))
    try:
        if hasattr(cls, "model_validate_json"):
            return cls.model_validate_json(text)
        data = json.loads(text)
        if not isinstance(data, Mapping):
            raise ValidationError(f"The response is not a JSON object for {name}", field="<root>", value=text)
        if not (isinstance(cls, type) and dataclasses.is_dataclass(cls)):
            raise ValidationError(f"response_schema must be a dataclass, got {cls!r}", field="response_schema", value=cls)
        missing = [
            f.name
            for f in dataclasses.fields(cls)
            if f.init
            and f.default is dataclasses.MISSING
            and f.default_factory is dataclasses.MISSING
            and f.name not in data
        ]
        if missing:
            raise ValidationError(f"The response lacks the field {missing[0]!r} of {name}", field=missing[0], value=text)
        instance = from_mapping(cls, data)
        validate_instance(instance)
        return instance
    except ValidationError:
        raise  # it already names the field
    except Exception as e:  # json errors, or a pydantic ValidationError
        errors = e.errors() if hasattr(e, "errors") else []
        field = ".".join(str(part) for part in errors[0]["loc"]) if errors and errors[0].get("loc") else "response_schema"
        raise ValidationError(f"The response does not conform to {name}: {e}", field=field, value=text) from e


def _parse_json_object(output: OutputSchema, text: str) -> dict[str, Any]:
    """The reply as a ``dict``, checked against the whole schema (types, nested objects, arrays, enums, required)."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValidationError(
            f"The response is not JSON for {output.name}: {e}", field="<root>", value=text
        ) from e
    if not isinstance(data, dict):
        raise ValidationError(
            f"The response is not a JSON object for {output.name}", field="<root>", value=text
        )
    check_json(data, output.schema, name=output.name, text=text)
    return data


__all__ = [
    "STRUCTURED_TOOL",
    "closed_schema",
    "parse_structured",
    "schema_instruction",
    "schema_name",
    "schema_of",
    "strict_schema",
    "wants_strict",
]
