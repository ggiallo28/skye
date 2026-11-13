"""Tests for the output block of the bundled ``extraction_generic`` prompt (json, table and xml through its ``format`` variable).

The prompt declares two conditional outputs, ``when schema { output F { schema = schema } }``
and ``when not schema { output F { name = string, value = string } }``: the format instructions
are generated from the ``schema`` variable (or the default fields) and appended to the last user
message.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from skye.base.dsl import PromptSpec, build
from skye.base.exceptions import ValidationError
from skye.base.messages import AssistantMessage, SkyeMessage, SystemMessage, UserMessage
from skye.prompts import BasePromptBuilder, load_prompt, output_instructions, render_prompt
from tests.unit.prompts.bundled import build_template, load_template

TEMPLATES = Path(__file__).resolve().parents[3] / "src" / "skye" / "prompts" / "templates"

TEMPLATE = "extraction_generic"
FORMATS = ("json", "table", "xml")

SCHEMA: dict[str, Any] = {"name": "string", "price": "number", "in_stock": "bool"}
NESTED_SCHEMA: dict[str, Any] = {
    "name": "string",
    "tags": ["string"],
    "vendor": {"city": "string"},
}
SCHEMAS = {"json": NESTED_SCHEMA, "table": SCHEMA, "xml": NESTED_SCHEMA}

TASK = "Extract the products"
INPUT = "Widget, 9.99 EUR, available. Gadget, 4 EUR, sold out."


def _load(name: str) -> PromptSpec:
    return load_template(TEMPLATES / f"{name}.skye", name)


def _content(message: SkyeMessage) -> str:
    content = message.content
    assert isinstance(content, str)
    return content


def _variables(fmt: str, **extra: Any) -> dict[str, Any]:
    return {"task": TASK, "input": INPUT, "schema": SCHEMAS[fmt], "format": fmt, **extra}


def _instructions(spec: PromptSpec, variables: dict[str, Any]) -> str:
    return str(output_instructions(spec, variables))


def _json_schemas(text: str) -> list[dict[str, Any]]:
    """Every JSON object in ``text`` that looks like a JSON Schema (has ``properties``)."""
    decoder = json.JSONDecoder()
    found: list[dict[str, Any]] = []
    index = text.find("{")
    while index != -1:
        try:
            value, end = decoder.raw_decode(text, index)
        except ValueError:
            index = text.find("{", index + 1)
            continue
        if isinstance(value, dict) and "properties" in value:
            found.append(value)
        index = text.find("{", end)
    return found


@pytest.fixture(params=FORMATS)
def fmt(request: pytest.FixtureRequest) -> str:
    return str(request.param)


def test_the_template_loads() -> None:
    path = TEMPLATES / f"{TEMPLATE}.skye"
    text = path.read_text(encoding="utf-8")
    metadata = build_template(path).metadata
    assert metadata["title"] and metadata["description"]
    assert metadata["version"] == "1.0"
    assert isinstance(metadata["tags"], list) and metadata["tags"]
    assert f'prompt "{TEMPLATE}"' in text
    spec = build_template(path).prompts[0]
    assert spec.output is None  # two conditional outputs instead
    (given, default) = spec.output_variants()
    assert [c.text for c in given[0]] == ["schema"]
    assert given[1].schema_from == "schema" and not given[1].fields  # the fields you pass...
    assert [c.text for c in default[0]] == ["not schema"]
    assert default[1].schema_from is None
    assert [(f.name, f.type) for f in default[1].fields] == [  # ...or these defaults
        ("name", "string"),
        ("value", "string"),
    ]
    assert given[1].format == default[1].format and given[1].format_from == default[1].format_from


def test_basic_render(fmt: str) -> None:
    messages = render_prompt(_load(TEMPLATE), _variables(fmt))
    assert isinstance(messages[0], SystemMessage)
    assert "precise data extractor" in _content(messages[0])
    assert "never invent" in _content(messages[0])
    last = messages[-1]
    assert isinstance(last, UserMessage)
    assert TASK in _content(last)
    assert INPUT in _content(last)


def test_last_user_message_ends_with_generated_instructions(fmt: str) -> None:
    spec = _load(TEMPLATE)
    variables = _variables(fmt)
    messages = render_prompt(spec, variables)
    instructions = _instructions(spec, variables)
    assert instructions.strip()
    assert _content(messages[-1]).rstrip().endswith(instructions.rstrip())
    # The instructions are generated only once, at the end of the last user message.
    assert sum(_content(m).count(instructions.strip()) for m in messages) == 1


def test_json_instructions_hold_a_json_schema() -> None:
    spec = _load(TEMPLATE)
    text = _content(render_prompt(spec, _variables("json"))[-1])
    schemas = _json_schemas(text)
    assert schemas, text
    properties = schemas[0]["properties"]
    assert set(NESTED_SCHEMA) <= set(properties)
    assert properties["name"]["type"] in ("string", ["string", "null"])
    assert "array" in json.dumps(properties["tags"])
    assert "city" in json.dumps(properties["vendor"])


def test_table_instructions_hold_the_header_row() -> None:
    spec = _load(TEMPLATE)
    text = _content(render_prompt(spec, _variables("table"))[-1])
    assert re.search(r"\|\s*name\s*\|\s*price\s*\|\s*in_stock\s*\|", text), text
    small = render_prompt(
        spec, {"task": TASK, "format": "table", "schema": {"a": "string", "b": "number"}}
    )
    assert "| a | b |" in _content(small[-1])


def test_xml_instructions_hold_the_skeleton() -> None:
    spec = _load(TEMPLATE)
    text = _content(render_prompt(spec, _variables("xml"))[-1])
    assert "<extraction_generic>" in text
    assert "</extraction_generic>" in text
    root = text[text.index("<extraction_generic>") : text.rindex("</extraction_generic>")]
    for child in ("name", "tags", "vendor", "city"):
        assert f"<{child}" in root, child


def test_task_and_input_are_optional(fmt: str) -> None:
    variables = _variables(fmt)
    del variables["task"]
    last = _content(render_prompt(_load(TEMPLATE), variables)[-1])
    assert INPUT in last and "## Task" not in last and "## Input" not in last
    del variables["input"]
    assert render_prompt(_load(TEMPLATE), variables)  # a task given later, in a history turn


def test_schema_has_a_default(fmt: str) -> None:
    # Without a schema the default fields, name and value (both strings), are asked for.
    variables = _variables(fmt)
    del variables["schema"]
    text = _content(render_prompt(_load(TEMPLATE), variables)[-1])
    for part in (
        "name",
        "value",
        "What the extracted item is",
        "Its value, as written in the input",
    ):
        assert part in text, part


def test_examples_become_message_pairs(fmt: str) -> None:
    examples = [
        {"input": "Lamp, 20 EUR", "output": "first answer"},
        {"input": "Desk, 80 EUR", "output": "second answer"},
    ]
    messages = render_prompt(_load(TEMPLATE), _variables(fmt, examples=examples))
    assert isinstance(messages[0], SystemMessage)
    pairs = messages[1:5]
    assert [type(m) for m in pairs] == [UserMessage, AssistantMessage] * 2
    assert [_content(m) for m in pairs] == [
        "Lamp, 20 EUR",
        "first answer",
        "Desk, 80 EUR",
        "second answer",
    ]
    assert TASK in _content(messages[-1])
    # The format instructions go to the task, not to the example turns.
    assert len(messages) == 6


def test_instructions_and_system_prompt(fmt: str) -> None:
    spec = _load(TEMPLATE)
    messages = render_prompt(spec, _variables(fmt, instructions=["Prices are in EUR"]))
    assert "- Prices are in EUR" in _content(messages[0])
    custom = render_prompt(spec, _variables(fmt, system_prompt="You are a custom extractor."))
    assert _content(custom[0]).startswith("You are a custom extractor.")
    assert "precise data extractor" not in _content(custom[0])


def test_history_placeholder(fmt: str) -> None:
    history = [{"role": "user", "content": "earlier"}, {"role": "assistant", "content": "reply"}]
    messages = render_prompt(_load(TEMPLATE), _variables(fmt), history={"history": history})
    assert [_content(m) for m in messages[1:3]] == ["earlier", "reply"]
    assert isinstance(messages[1], UserMessage)
    assert isinstance(messages[2], AssistantMessage)
    assert TASK in _content(messages[-1])


def test_builder_render(fmt: str) -> None:
    builder = BasePromptBuilder()
    variables = _variables(fmt)
    messages = builder.render(TEMPLATE, variables)
    direct = render_prompt(_load(TEMPLATE), variables)
    assert [(type(m), _content(m)) for m in messages] == [(type(m), _content(m)) for m in direct]


def test_builder_output_instructions(fmt: str) -> None:
    builder = BasePromptBuilder()
    variables = _variables(fmt)
    expected = _instructions(_load(TEMPLATE), variables)
    got = builder.get_output_instructions(TEMPLATE, variables)
    assert got.strip()
    assert got.strip() == expected.strip()


# -- extraction_generic: the format comes from the ``format`` variable ----------------------------

DESCRIBED_SCHEMA: dict[str, Any] = {
    "name": {"type": "string", "description": "Product name"},
    "price": {"type": "number", "description": "Unit price in EUR"},
    "in_stock": "bool",
}


def test_the_usage_comment_schemas_work_as_shown() -> None:
    """The ``schema`` maps of the usage comments above the ``output`` lines."""
    spec = _load(TEMPLATE)
    schema = {
        "vendor": {"type": "string", "description": "Seller name as printed"},
        "total": {"type": "number", "description": "Total including VAT"},
        "paid": "bool",
        "tags": ["string"],
        "lines": [{"description": "string", "amount": "number"}],
        "address": {"city": "string", "zip": "string"},
    }
    (found,) = _json_schemas(_instructions(spec, {"schema": schema, "format": "json"}))
    properties = found["properties"]
    assert properties["vendor"] == {"type": "string", "description": "Seller name as printed"}
    assert properties["total"] == {"type": "number", "description": "Total including VAT"}
    assert properties["lines"]["items"]["properties"]["description"] == {"type": "string"}
    assert properties["address"]["properties"] == {
        "city": {"type": "string"},
        "zip": {"type": "string"},
    }
    table = _instructions(spec, {"schema": DESCRIBED_SCHEMA, "format": "table"})
    assert table.endswith(
        "- name: string — Product name\n- price: number — Unit price in EUR\n"
        "- in_stock: true or false"
    )


def test_structured_output_loads_and_defaults_to_json() -> None:
    metadata = build_template(TEMPLATES / f"{TEMPLATE}.skye").metadata
    assert metadata["title"] == "Generic extraction" and metadata["version"] == "1.0"
    assert metadata["tags"] == ["extraction", "classification", "structured-output"]
    spec = _load(TEMPLATE)
    assert [o.format_from for _, o in spec.output_variants()] == ["format", "format"]
    default = _instructions(spec, {"schema": DESCRIBED_SCHEMA})
    assert default == _instructions(spec, {"schema": DESCRIBED_SCHEMA, "format": "json"})
    assert default.startswith("Answer with a single JSON object")


@pytest.mark.parametrize("fmt", ["json", "table", "xml"])
@pytest.mark.parametrize("schema", [SCHEMA, DESCRIBED_SCHEMA])
def test_the_format_variable_picks_the_instructions_of_the_user_message(
    fmt: str, schema: dict[str, Any]
) -> None:
    spec = _load(TEMPLATE)
    got = _instructions(spec, {"schema": schema, "format": fmt})
    assert got.strip()
    messages = render_prompt(spec, {"task": TASK, "schema": schema, "format": fmt})
    assert _content(messages[-1]).endswith(got)
    assert {"json": "JSON object", "table": "table", "xml": "XML only"}[fmt] in got


def test_structured_output_rejects_a_bad_format_and_a_nested_table() -> None:
    spec = _load(TEMPLATE)
    with pytest.raises(ValidationError, match="'csv' is not one of json, table, xml or text"):
        _instructions(spec, {"schema": SCHEMA, "format": "csv"})
    with pytest.raises(ValidationError, match="'tags'"):
        _instructions(spec, {"schema": NESTED_SCHEMA, "format": "table"})
    assert "<tags>" in _instructions(spec, {"schema": NESTED_SCHEMA, "format": "xml"})


def test_structured_output_system_rule_covers_every_format() -> None:
    system = _content(
        render_prompt(_load(TEMPLATE), _variables("json"))[0]
    )
    assert "null in JSON" in system and "empty cell" in system and "empty element" in system


SAME_SCHEMA: dict[str, Any] = {
    "name": {"type": "string", "description": "Product name"},
    "price": {"type": "number", "description": "Unit price in EUR"},
    "in_stock": "bool",
}
SAME_DESCRIPTIONS = ("Product name", "Unit price in EUR")


def _check_shape(fmt: str, text: str) -> None:
    for field_name in SAME_SCHEMA:
        assert field_name in text, field_name
    for description in SAME_DESCRIPTIONS:
        assert description in text, description
    if fmt == "json":
        found = json.loads(text.split("```json\n", 1)[1].split("```", 1)[0])
        assert found["properties"] == {
            "name": {"type": "string", "description": "Product name"},
            "price": {"type": "number", "description": "Unit price in EUR"},
            "in_stock": {"type": "boolean"},
        }
    elif fmt == "table":
        assert "| name | price | in_stock |" in text
    else:
        root = text[text.index("<extraction_generic>") : text.index("</extraction_generic>")]
        for child in ("<name>", "<price>", "<in_stock>"):
            assert child in root, child


@pytest.mark.parametrize("fmt", ["json", "table", "xml"])
def test_structured_output_same_schema_every_format(fmt: str) -> None:
    spec = _load(TEMPLATE)
    variables = {"task": TASK, "input": INPUT, "schema": SAME_SCHEMA, "format": fmt}
    instructions = _instructions(spec, variables)
    messages = render_prompt(spec, variables)
    assert isinstance(messages[-1], UserMessage)
    assert _content(messages[-1]).endswith(instructions)
    _check_shape(fmt, instructions)
    built = BasePromptBuilder().render(TEMPLATE, variables)
    assert _content(built[-1]).endswith(instructions)
    _check_shape(fmt, _content(built[-1]))


NESTED_SAME: dict[str, Any] = {
    "vendor": {"type": "string", "description": "Seller name"},
    "lines": [{"description": "string", "amount": {"type": "number", "description": "Amount"}}],
    "address": {"city": "string", "zip": "string"},
}


@pytest.mark.parametrize("fmt", ["json", "xml", "table"])
def test_structured_output_same_nested_schema(fmt: str) -> None:
    spec = _load(TEMPLATE)
    variables = {"task": TASK, "schema": NESTED_SAME, "format": fmt}
    if fmt == "table":
        with pytest.raises(ValidationError, match="'lines'"):
            render_prompt(spec, variables)
        return
    text = _content(render_prompt(spec, variables)[-1])
    for word in ("vendor", "lines", "amount", "address", "city", "zip", "Seller name", "Amount"):
        assert word in text, word
    if fmt == "json":
        found = json.loads(text.split("```json\n", 1)[1].split("```", 1)[0])
        lines = found["properties"]["lines"]
        assert lines["type"] == "array"
        assert lines["items"]["properties"]["amount"] == {"type": "number", "description": "Amount"}
        assert found["properties"]["address"]["properties"]["city"] == {"type": "string"}
    else:
        assert "<lines>\n    <item>" in text and "<address>\n    <city>string</city>" in text


# -- with and without a schema: the conditional outputs ----------------------------------------

DEFAULT_DESCRIPTIONS = ("What the extracted item is", "Its value, as written in the input")


@pytest.mark.parametrize("format_", ["json", "xml"])
def test_render_with_and_without_schema(format_: str) -> None:
    spec = _load(TEMPLATE)
    extra = {"format": format_}
    with_schema = _content(
        render_prompt(spec, {"task": TASK, "schema": NESTED_SCHEMA, **extra})[-1]
    )
    assert "tags" in with_schema and "city" in with_schema
    assert not any(d in with_schema for d in DEFAULT_DESCRIPTIONS)
    for schema in (None, {}):
        variables = (
            {"task": TASK, **extra} if schema is None else {"task": TASK, "schema": schema, **extra}
        )
        without = _content(render_prompt(spec, variables)[-1])
        assert all(d in without for d in DEFAULT_DESCRIPTIONS)
        assert "tags" not in without
        if format_ == "xml":
            assert "<extraction_generic>" in without and "<name>" in without
        else:
            assert without.count("Answer with a single JSON object") == 1
            (found,) = _json_schemas(without)
            assert list(found["properties"]) == ["name", "value"]


def test_the_default_format_is_json_with_and_without_schema() -> None:
    spec = _load(TEMPLATE)
    without = _content(render_prompt(spec, {"task": TASK})[-1])
    assert without.count("Answer with a single JSON object") == 1


def test_table_with_and_without_schema() -> None:
    spec = _load(TEMPLATE)
    extra = {"format": "table"}
    given = _content(render_prompt(spec, {"task": TASK, "schema": SCHEMA, **extra})[-1])
    assert re.search(r"\|\s*name\s*\|\s*price\s*\|\s*in_stock\s*\|", given), given
    default = _content(render_prompt(spec, {"task": TASK, **extra})[-1])
    assert "| name | value |" in default
    assert "- name: string — What the extracted item is" in default


def test_structured_output_help_shows_both_variants() -> None:
    from skye.prompts import describe_prompt, prompt_help

    text = prompt_help(describe_prompt(_load(TEMPLATE)))
    assert "Output (when schema): from variable format\n  fields from variable schema" in text
    assert "Output (when not schema): from variable format\n  name " in text


def test_builder_render_with_and_without_schema(fmt: str) -> None:
    builder = BasePromptBuilder()
    for variables in (
        {"task": TASK, "schema": SCHEMAS[fmt], "format": fmt},
        {"task": TASK, "format": fmt},
    ):
        got = builder.render(TEMPLATE, variables)
        direct = render_prompt(_load(TEMPLATE), variables)
        assert [_content(m) for m in got] == [_content(m) for m in direct]
    default = builder.get_output_instructions(TEMPLATE, {"task": TASK, "format": fmt})
    assert all(d in default for d in DEFAULT_DESCRIPTIONS)
