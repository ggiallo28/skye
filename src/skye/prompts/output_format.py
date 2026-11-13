# D70
"""Instructions that ask a model to answer in a given format: JSON, a Markdown table or XML.

The shape of the answer is a JSON Schema (``type: object`` with ``properties``); it comes from the
``output`` block of a ``.skye`` prompt (:func:`fields_schema`), from a map variable given at
render time (:func:`fields_from_value`), or from :meth:`BasePromptBuilder.set_output_schema` (a
dataclass or a JSON-schema dictionary). :func:`format_instructions` writes the text, in plain
English and always the same for the same schema, so nobody writes the structure of the answer by
hand.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from skye.base.dsl import OUTPUT_FORMATS, OutputFieldSpec
from skye.base.exceptions import ValidationError

_JSON_TYPES = {"string": "string", "number": "number", "bool": "boolean"}
_TYPE_WORDS = ("string", "number", "bool", "list", "map")
#: The keys of a field written as ``{"type": ..., "description": ...}`` in a ``schema = VAR`` map.
_DESCRIPTOR_KEYS = frozenset({"type", "description", "items", "properties"})
_INDENT = "  "


def check_format(output_format: str) -> str:
    """Return ``output_format`` if it is ``json``, ``table``, ``xml`` or ``text``; raise otherwise.

    Raises:
        ValidationError: If the format is not one of the four.
    """
    if output_format not in OUTPUT_FORMATS:
        raise ValidationError(
            f"Unknown output format {output_format!r}: use json, table, xml or text",
            field="output_format",
            value=output_format,
            supported=list(OUTPUT_FORMATS),
        )
    return output_format


# -- fields -> JSON Schema ---------------------------------------------------------------------


def fields_schema(fields: Sequence[OutputFieldSpec]) -> dict[str, Any]:
    """The JSON Schema of an object with these fields (``required``: those without default)."""
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {f.name: _field_schema(f) for f in fields},
    }
    required = [f.name for f in fields if f.required]
    if required:
        schema["required"] = required
    return schema


def _field_schema(item: OutputFieldSpec) -> dict[str, Any]:
    schema = _type_schema(item)
    if item.description is None:
        return schema
    kind = schema.pop("type")  # the description comes right after the type
    return {"type": kind, "description": item.description, **schema}


def _type_schema(item: OutputFieldSpec) -> dict[str, Any]:
    if item.type == "list":
        schema: dict[str, Any] = {"type": "array"}
        if item.item_type == "map":
            schema["items"] = fields_schema(item.fields) if item.fields else {"type": "object"}
        elif item.item_type is not None:
            schema["items"] = {"type": _JSON_TYPES.get(item.item_type, "array")}
        return schema
    if item.type == "map":
        return fields_schema(item.fields) if item.fields else {"type": "object"}
    schema = {"type": _JSON_TYPES[item.type]}
    if not item.required and item.default is not None:
        schema["default"] = item.default
    return schema


def fields_from_value(value: Any, where: str) -> list[OutputFieldSpec]:
    """The fields given by the value of a ``schema = VAR`` variable.

    Args:
        value: A mapping ``{name: kind}`` where ``kind`` is ``"string"``, ``"number"``, ``"bool"``,
            ``"list"``, ``"map"``, a one-item list ``[kind]`` (a list of that kind), a nested
            mapping (an object with those fields) or a described field
            ``{"type": word, "description": text}``: a mapping with a ``"type"`` key and no key
            but ``type``, ``description``, ``items`` (a list: the ``kind`` of its items) and
            ``properties`` (a map: its fields, as in ``value``). An object with a field named
            ``type`` is written ``{"type": "map", "properties": {"type": "string"}}``.
        where: The name used in the error messages (the variable).

    Raises:
        ValidationError: If the value does not have that shape; the message names the field.
    """
    if not isinstance(value, Mapping) or not value:
        raise ValidationError(
            f"output schema {where!r}: expected a map of field names to types, such as "
            '{"name": "string", "price": "number"}',
            field=where,
            value=repr(value),
        )
    return [_field_from_value(str(name), kind, f"{where}.{name}") for name, kind in value.items()]


def _field_from_value(name: str, kind: Any, where: str) -> OutputFieldSpec:
    if isinstance(kind, Mapping) and "type" in kind and set(kind) <= _DESCRIPTOR_KEYS:
        return _described_field(name, kind, where)
    if isinstance(kind, Mapping):
        return OutputFieldSpec(name=name, type="map", fields=fields_from_value(kind, where))
    if isinstance(kind, list | tuple):
        if len(kind) != 1:
            raise ValidationError(
                f'output schema {where!r}: a list type has one item type, such as ["string"]',
                field=where,
                value=repr(kind),
            )
        inner = _field_from_value(name, kind[0], where)
        if inner.description is not None:
            raise ValidationError(
                f"output schema {where!r}: the items of a list have no description of their "
                'own; describe the list: {"type": "list", "items": ..., "description": "..."}',
                field=where,
                value=repr(kind),
            )
        if inner.type == "list":
            raise ValidationError(
                f"output schema {where!r}: the items of a list are string, number, bool or a map",
                field=where,
                value=repr(kind),
            )
        return OutputFieldSpec(
            name=name, type="list", item_type=inner.type, fields=list(inner.fields)
        )
    if isinstance(kind, str) and kind in _TYPE_WORDS:
        return OutputFieldSpec(name=name, type=kind)  # type: ignore[arg-type]
    raise ValidationError(
        f"output schema {where!r}: unknown type {kind!r}; use string, number, bool, list, map, "
        "[type] or a nested map",
        field=where,
        value=repr(kind),
    )


def _described_field(name: str, kind: Mapping[str, Any], where: str) -> OutputFieldSpec:
    """``{"type": word, "description": text, "items": kind, "properties": {...}}``."""

    def fail(reason: str) -> ValidationError:
        return ValidationError(f"output schema {where!r}: {reason}", field=where, value=repr(kind))

    word, text = kind["type"], kind.get("description")
    if not (isinstance(word, str) and word in _TYPE_WORDS):
        raise fail(f'unknown type {word!r} in "type"; use string, number, bool, list or map')
    if text is not None and not (isinstance(text, str) and text.strip()):
        raise fail('"description" must be a non-empty string')
    if "items" in kind and word != "list":
        raise fail(f'"items" is for a list, and the type is {word!r}')
    if "properties" in kind and word != "map":
        raise fail(f'"properties" is for a map, and the type is {word!r}')
    if "items" in kind:
        inner = _field_from_value(name, [kind["items"]], where)
        field = OutputFieldSpec(
            name=name, type="list", item_type=inner.item_type, fields=list(inner.fields)
        )
    elif "properties" in kind:
        field = OutputFieldSpec(
            name=name, type="map", fields=fields_from_value(kind["properties"], f"{where}")
        )
    else:
        field = OutputFieldSpec(name=name, type=word)  # type: ignore[arg-type]
    return field if text is None else replace(field, description=text)


# -- JSON Schema -> instructions ---------------------------------------------------------------


def format_instructions(schema: Mapping[str, Any], output_format: str, name: str) -> str:
    """The instructions that ask for an answer of this shape in this format.

    Args:
        schema: A JSON Schema; ``table`` needs an object whose properties are all scalar; for
            ``text`` it is ``{"style": "..."}`` (the style may be absent or empty).
        output_format: ``json``, ``table``, ``xml`` or ``text``.
        name: The prompt or template name: the root element of the XML (in snake_case).

    Raises:
        ValidationError: If the format is unknown, or a ``table`` has a nested (list or map)
            column (the message names it).
    """
    check_format(output_format)
    if output_format == "text":
        style = schema.get("style")
        return "Answer in plain text" + (
            f": {style}." if style else ", with no JSON, table or markup around it."
        )
    if output_format == "table":
        return _table(schema)
    if output_format == "xml":
        return _xml_text(schema, name)
    return _json(schema)


def _json(schema: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            "Answer with a single JSON object and nothing else.",
            "It must match this JSON Schema:",
            "```json",
            json.dumps(schema, indent=2, ensure_ascii=False),
            "```",
            "Example of the shape:",
            json.dumps(_example(schema), ensure_ascii=False),
        ]
    )


def _example(schema: Mapping[str, Any]) -> Any:
    if "default" in schema:
        return schema["default"]
    if schema.get("enum"):
        return schema["enum"][0]
    kind = schema.get("type")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), None)
    if kind == "object" or isinstance(schema.get("properties"), Mapping):
        properties = schema.get("properties")
        if not isinstance(properties, Mapping):
            return {}
        return {k: _example(v) for k, v in properties.items() if isinstance(v, Mapping)}
    if kind == "array":
        items = schema.get("items")
        return [_example(items)] if isinstance(items, Mapping) and items else []
    if "anyOf" in schema and schema["anyOf"]:
        return _example(schema["anyOf"][0])
    return {"string": "...", "number": 0, "integer": 0, "boolean": False}.get(str(kind))


def _hint(schema: Mapping[str, Any]) -> str:
    """The type of a scalar in words: ``string``, ``number``, ``true or false``, ``one of ...``."""
    if "enum" in schema:
        text = "one of " + ", ".join(json.dumps(v, ensure_ascii=False) for v in schema["enum"])
    elif "anyOf" in schema:
        text = " or ".join(_hint(s) for s in schema["anyOf"] if isinstance(s, Mapping))
    else:
        kind = schema.get("type")
        kinds = kind if isinstance(kind, list) else [kind] if kind else []
        words = {"boolean": "true or false", "array": "list", "object": "map"}
        text = " or ".join(words.get(str(k), str(k)) for k in kinds) or "any"
    if "default" in schema:
        text += f" (default {json.dumps(schema['default'], ensure_ascii=False)})"
    return text


def _nested(schema: Mapping[str, Any]) -> bool:
    kind = schema.get("type")
    kinds = kind if isinstance(kind, list) else [kind]
    return (
        "array" in kinds
        or "object" in kinds
        or "properties" in schema
        or "items" in schema
        or any(_nested(s) for s in schema.get("anyOf", ()) if isinstance(s, Mapping))
    )


def _table(schema: Mapping[str, Any]) -> str:
    properties = schema.get("properties")
    if not isinstance(properties, Mapping) or not properties:
        raise ValidationError(
            "A table output needs an object schema with properties (the columns)",
            field="schema",
            value=dict(schema),
        )
    for column, sub in properties.items():
        if not isinstance(sub, Mapping) or _nested(sub):
            raise ValidationError(
                f"Column {column!r} is a list or a map; a table has only string, number and "
                "bool columns. Use the json or xml format for nested data",
                field=str(column),
                value=dict(sub) if isinstance(sub, Mapping) else repr(sub),
            )
    names = [str(c) for c in properties]
    lines = [
        "Answer with a Markdown table and nothing else, one row per item, with these columns:",
        "| " + " | ".join(names) + " |",
        "|" + "---|" * len(names),
    ]
    lines.extend(f"- {c}: {_hint(properties[c])}{_note(properties[c])}" for c in names)
    return "\n".join(lines)


def _description(schema: Mapping[str, Any]) -> str:
    """The ``description`` of a schema on one line ("" when it has none)."""
    text = schema.get("description")
    return " ".join(text.split()) if isinstance(text, str) else ""


def _note(schema: Mapping[str, Any]) -> str:
    """`` — description`` after the type of a table column or an XML leaf ("" without one)."""
    text = _description(schema)
    return f" \u2014 {text}" if text else ""


def _comment(schema: Mapping[str, Any]) -> str:
    """`` <!-- description -->`` after the opening tag of an XML element with children."""
    text = _description(schema).replace("--", "- -")
    return f" <!-- {text} -->" if text else ""


def xml_name(name: str) -> str:
    """``name`` as an XML element name in snake_case (``ExtractInvoice``: ``extract_invoice``)."""
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    text = re.sub(r"[^0-9A-Za-z_]+", "_", text).strip("_").lower()
    if not text:
        return "output"
    return f"_{text}" if text[0].isdigit() else text


def _xml_text(schema: Mapping[str, Any], name: str) -> str:
    lines = ["Answer with XML only, no text around it, in this shape:"]
    has_list = _xml(xml_name(name), schema, 0, lines)
    if has_list:
        lines.append("Repeat <item> once for each element of a list.")
    return "\n".join(lines)


def _xml(tag: str, schema: Mapping[str, Any], depth: int, out: list[str]) -> bool:
    """Append the skeleton of one element; return True when a list is inside it."""
    pad = _INDENT * depth
    properties = schema.get("properties")
    if isinstance(properties, Mapping) and properties:
        out.append(f"{pad}<{tag}>{_comment(schema)}")
        found = False
        for key, sub in properties.items():
            if isinstance(sub, Mapping):
                found = _xml(str(key), sub, depth + 1, out) or found
        out.append(f"{pad}</{tag}>")
        return found
    items = schema.get("items")
    if schema.get("type") == "array" and isinstance(items, Mapping) and items:
        out.append(f"{pad}<{tag}>{_comment(schema)}")
        _xml("item", items, depth + 1, out)
        out.append(f"{pad}</{tag}>")
        return True
    out.append(f"{pad}<{tag}>{_hint(schema)}{_note(schema)}</{tag}>")
    return schema.get("type") == "array"


__all__ = [
    "OUTPUT_FORMATS",
    "check_format",
    "fields_from_value",
    "fields_schema",
    "format_instructions",
    "xml_name",
]
