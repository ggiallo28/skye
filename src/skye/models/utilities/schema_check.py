# Requirement 27.2
"""A small JSON Schema check for structured replies (standard library only).

It covers what output schemas use: ``type`` (one or a list; an integer is never a boolean),
``properties``, ``required``, ``additionalProperties`` (``false`` or a schema), ``items`` (one
schema or a list), ``prefixItems``, ``enum``, ``const``, ``anyOf``, ``oneOf``, ``allOf``, ``not``,
``$ref`` to ``#/$defs/...`` or ``#/definitions/...``, ``minItems``/``maxItems``,
``uniqueItems``, ``minLength``/``maxLength``, ``pattern``, ``minimum``/``maximum`` and their
exclusive forms, ``multipleOf``, ``minProperties``/``maxProperties``. A keyword it does not know
(``format``, ``title``, ``description``, ...) is ignored, as JSON Schema says.

The first problem is raised as ``ValidationError`` whose ``field`` is the path of the value
(``address.city``, ``tags[1]``, ``<root>``).

Example:
    >>> check_json({"age": 3}, {"type": "object", "properties": {"age": {"type": "integer"}}})
    >>> schema = {"type": "object", "properties": {"age": {"type": "integer"}}}
    >>> check_json({"age": "3"}, schema, name="person")
    Traceback (most recent call last):...
    skye.base.exceptions.ValidationError: The response does not conform to person: ...
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from skye.base.exceptions import ValidationError

_TYPES: dict[str, Any] = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int)
    and not isinstance(v, bool)
    or isinstance(v, float)
    and v.is_integer(),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


class _MismatchError(Exception):
    def __init__(self, path: str, reason: str) -> None:
        super().__init__(reason)
        self.path = path
        self.reason = reason


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _label(path: str) -> str:
    return path or "<root>"


def _resolve(ref: str, root: Mapping[str, Any]) -> Mapping[str, Any]:
    if not ref.startswith("#/"):
        raise _MismatchError("", f"cannot follow the reference {ref!r}")
    node: Any = root
    for part in ref[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, Mapping) or part not in node:
            raise _MismatchError("", f"cannot follow the reference {ref!r}")
        node = node[part]
    return node  # type: ignore[no-any-return]


def _equal(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    return bool(a == b)


def _check(value: Any, schema: Any, path: str, root: Mapping[str, Any]) -> None:
    if schema is True or schema == {}:
        return
    if schema is False:
        raise _MismatchError(path, f"{_label(path)} is not allowed")
    if not isinstance(schema, Mapping):
        return
    if "$ref" in schema:
        _check(value, _resolve(schema["$ref"], root), path, root)

    kind = schema.get("type")
    if kind is not None:
        kinds = [kind] if isinstance(kind, str) else list(kind)
        if not any(_TYPES.get(k, lambda v: True)(value) for k in kinds):
            raise _MismatchError(path, f"{_label(path)} is not of type {' or '.join(kinds)}")

    if "enum" in schema and not any(_equal(value, option) for option in schema["enum"]):
        raise _MismatchError(path, f"{_label(path)} is not one of {json.dumps(schema['enum'])}")
    if "const" in schema and not _equal(value, schema["const"]):
        raise _MismatchError(path, f"{_label(path)} is not {json.dumps(schema['const'])}")

    for sub in schema.get("allOf", []):
        _check(value, sub, path, root)
    if "anyOf" in schema and not _matches_any(value, schema["anyOf"], path, root):
        raise _MismatchError(path, f"{_label(path)} matches none of the allowed shapes")
    if "oneOf" in schema:
        matched = sum(_matches(value, sub, path, root) for sub in schema["oneOf"])
        if matched != 1:
            raise _MismatchError(
                path, f"{_label(path)} matches {matched} of the shapes, not exactly one"
            )
    if "not" in schema and _matches(value, schema["not"], path, root):
        raise _MismatchError(path, f"{_label(path)} matches a shape it must not match")

    if isinstance(value, dict):
        _check_object(value, schema, path, root)
    elif isinstance(value, list):
        _check_array(value, schema, path, root)
    elif isinstance(value, str):
        _check_string(value, schema, path)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        _check_number(value, schema, path)


def _matches(value: Any, schema: Any, path: str, root: Mapping[str, Any]) -> bool:
    try:
        _check(value, schema, path, root)
    except _MismatchError:
        return False
    return True


def _matches_any(value: Any, schemas: list[Any], path: str, root: Mapping[str, Any]) -> bool:
    return any(_matches(value, sub, path, root) for sub in schemas)


def _check_object(
    value: dict[str, Any], schema: Mapping[str, Any], path: str, root: Mapping[str, Any]
) -> None:
    for key in schema.get("required", []):
        if key not in value:
            where = _join(path, str(key))
            raise _MismatchError(where, f"it lacks the field {where!r}")
    properties = schema.get("properties", {})
    extra = schema.get("additionalProperties", True)
    for key, item in value.items():
        if key in properties:
            _check(item, properties[key], _join(path, key), root)
        elif extra is False:
            raise _MismatchError(_join(path, key), f"the field {_join(path, key)} is not allowed")
        elif isinstance(extra, Mapping):
            _check(item, extra, _join(path, key), root)
    if "minProperties" in schema and len(value) < schema["minProperties"]:
        minimum = schema["minProperties"]
        raise _MismatchError(path, f"{_label(path)} has fewer than {minimum} fields")
    if "maxProperties" in schema and len(value) > schema["maxProperties"]:
        raise _MismatchError(path, f"{_label(path)} has more than {schema['maxProperties']} fields")


def _check_array(
    value: list[Any], schema: Mapping[str, Any], path: str, root: Mapping[str, Any]
) -> None:
    prefix = schema.get("prefixItems")
    items = schema.get("items")
    if isinstance(items, list):  # the older tuple form
        prefix, items = items, schema.get("additionalItems", True)
    prefix = prefix or []
    for index, item in enumerate(value):
        sub = prefix[index] if index < len(prefix) else items
        if sub is not None:
            _check(item, sub, f"{path}[{index}]", root)
    if "minItems" in schema and len(value) < schema["minItems"]:
        raise _MismatchError(path, f"{_label(path)} has fewer than {schema['minItems']} items")
    if "maxItems" in schema and len(value) > schema["maxItems"]:
        raise _MismatchError(path, f"{_label(path)} has more than {schema['maxItems']} items")
    if schema.get("uniqueItems"):
        seen = [json.dumps(item, sort_keys=True) for item in value]
        if len(set(seen)) != len(seen):
            raise _MismatchError(path, f"{_label(path)} has repeated items")


def _check_string(value: str, schema: Mapping[str, Any], path: str) -> None:
    if "minLength" in schema and len(value) < schema["minLength"]:
        raise _MismatchError(path, f"{_label(path)} is shorter than {schema['minLength']}")
    if "maxLength" in schema and len(value) > schema["maxLength"]:
        raise _MismatchError(path, f"{_label(path)} is longer than {schema['maxLength']}")
    if "pattern" in schema and re.search(schema["pattern"], value) is None:
        raise _MismatchError(path, f"{_label(path)} does not match {schema['pattern']!r}")


def _check_number(value: float, schema: Mapping[str, Any], path: str) -> None:
    label = _label(path)
    if "minimum" in schema and value < schema["minimum"]:
        raise _MismatchError(path, f"{label} is less than {schema['minimum']}")
    if "maximum" in schema and value > schema["maximum"]:
        raise _MismatchError(path, f"{label} is greater than {schema['maximum']}")
    if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
        raise _MismatchError(path, f"{label} is not greater than {schema['exclusiveMinimum']}")
    if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
        raise _MismatchError(path, f"{label} is not less than {schema['exclusiveMaximum']}")
    step = schema.get("multipleOf")
    if step and (value / step) != int(value / step):
        raise _MismatchError(path, f"{label} is not a multiple of {step}")


def check_json(
    value: Any, schema: Mapping[str, Any], *, name: str = "the schema", text: str | None = None
) -> None:
    """Check a decoded JSON value against a JSON Schema.

    Args:
        value: The decoded reply.
        schema: The JSON Schema.
        name: The name of the schema, for the message.
        text: The raw reply, kept as the error's ``value`` (the decoded value when omitted).

    Raises:
        ValidationError: The first problem; ``field`` is the path of the value (``<root>`` for
            the whole reply).
    """
    try:
        _check(value, schema, "", schema)
    except _MismatchError as problem:
        raise ValidationError(
            f"The response does not conform to {name}: {problem.reason}",
            field=_label(problem.path),
            value=value if text is None else text,
        ) from None


__all__ = ["check_json"]
