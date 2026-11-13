"""Structured output (D70): the instructions of the ``.skye`` ``output`` block, the builder's
``output_format`` and the engine filters ``toxml`` and ``totable``."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace

import pytest

from skye.base.exceptions import ValidationError
from skye.base.messages import SystemMessage, UserMessage
from skye.prompts import BasePromptBuilder, load_prompt, output_instructions, render_prompt
from skye.prompts.engine import render_template

SMALL = """
prompt "ItemList" {
  variables = { text = string }
  output "%s" { name = string, price = number(0), in_stock = bool }
  message "system" { text = "You read catalogues." }
  message "user" { text = "Catalogue: {{ text }}" }
}
"""

JSON_TEXT = """Answer with a single JSON object and nothing else.
It must match this JSON Schema:
```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string"
    },
    "price": {
      "type": "number",
      "default": 0
    },
    "in_stock": {
      "type": "boolean"
    }
  },
  "required": [
    "name",
    "in_stock"
  ]
}
```
Example of the shape:
{"name": "...", "price": 0, "in_stock": false}"""

TABLE_TEXT = """Answer with a Markdown table and nothing else, one row per item, with these columns:
| name | price | in_stock |
|---|---|---|
- name: string
- price: number (default 0)
- in_stock: true or false"""

XML_TEXT = """Answer with XML only, no text around it, in this shape:
<item_list>
  <name>string</name>
  <price>number (default 0)</price>
  <in_stock>true or false</in_stock>
</item_list>"""


@pytest.mark.parametrize(
    "fmt,expected", [("json", JSON_TEXT), ("table", TABLE_TEXT), ("xml", XML_TEXT)]
)
def test_exact_text_of_each_format(fmt: str, expected: str) -> None:
    spec = load_prompt(SMALL % fmt)
    assert output_instructions(spec) == expected
    messages = render_prompt(spec, {"text": "A lamp"})
    assert [type(m) for m in messages] == [SystemMessage, UserMessage]
    assert messages[0].content == "You read catalogues."
    assert messages[1].content == f"Catalogue: A lamp\n\n{expected}"


def test_nested_json_and_xml() -> None:
    spec = load_prompt(
        'prompt "extract_invoice" {\n  variables = { document = string }\n'
        '  output "json" { vendor = string, currency = string("EUR"), '
        "lines = list({ description = string, amount = number }), tags = [string], "
        "meta = map({ source = string }) }\n"
        '  message "user" { text = "{{ document }}" }\n}\n'
    )
    text = output_instructions(spec)
    schema = json.loads(text.split("```json\n")[1].split("\n```")[0])
    assert schema["required"] == ["vendor", "lines", "tags", "meta"]
    assert schema["properties"]["lines"] == {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {"description": {"type": "string"}, "amount": {"type": "number"}},
            "required": ["description", "amount"],
        },
    }
    assert schema["properties"]["tags"] == {"type": "array", "items": {"type": "string"}}
    assert text.endswith(
        '{"vendor": "...", "currency": "EUR", "lines": [{"description": "...", "amount": 0}], '
        '"tags": ["..."], "meta": {"source": "..."}}'
    )
    assert spec.output is not None
    xml = output_instructions(replace(spec, output=replace(spec.output, format="xml")))
    assert xml == (
        "Answer with XML only, no text around it, in this shape:\n"
        "<extract_invoice>\n"
        "  <vendor>string</vendor>\n"
        '  <currency>string (default "EUR")</currency>\n'
        "  <lines>\n"
        "    <item>\n"
        "      <description>string</description>\n"
        "      <amount>number</amount>\n"
        "    </item>\n"
        "  </lines>\n"
        "  <tags>\n"
        "    <item>string</item>\n"
        "  </tags>\n"
        "  <meta>\n"
        "    <source>string</source>\n"
        "  </meta>\n"
        "</extract_invoice>\n"
        "Repeat <item> once for each element of a list."
    )


def test_no_output_block_gives_nothing_and_changes_nothing() -> None:
    spec = load_prompt('prompt "p" { message "user" { text = "hi" } }')
    assert output_instructions(spec) == ""
    assert [m.content for m in render_prompt(spec, {})] == ["hi"]


def test_a_prompt_without_a_user_message_gets_one() -> None:
    spec = load_prompt(
        'prompt "p" {\n  output "table" { a = string }\n  message "system" { text = "s" }\n}\n'
    )
    messages = render_prompt(spec, {})
    assert [type(m) for m in messages] == [SystemMessage, UserMessage]
    assert messages[1].content == output_instructions(spec)


def test_the_last_user_message_is_the_one_that_gets_it() -> None:
    spec = load_prompt(
        'prompt "p" {\n  output { a = string }\n  message "user" { text = "one" }\n'
        '  message "assistant" { text = "two" }\n  message "user" { text = "three" }\n'
        '  message "assistant" { text = "four" }\n}\n'
    )
    contents = [m.content for m in render_prompt(spec, {})]
    assert contents[:2] == ["one", "two"] and contents[3] == "four"
    assert contents[2].startswith("three\n\nAnswer with a single JSON object")


DYNAMIC = """
prompt "dyn" {
  variables = { fields = map({ name = "string" }), text = string("") }
  output "%s" { schema = fields }
  message "user" { text = "go" }
}
"""


def test_dynamic_schema_reads_the_variable() -> None:
    spec = load_prompt(DYNAMIC % "xml")
    fields = {"a": "string", "tags": ["string"], "sub": {"x": "bool"}, "rows": [{"n": "number"}]}
    text = output_instructions(spec, {"fields": fields})
    assert text == (
        "Answer with XML only, no text around it, in this shape:\n<dyn>\n  <a>string</a>\n"
        "  <tags>\n    <item>string</item>\n  </tags>\n"
        "  <sub>\n    <x>true or false</x>\n  </sub>\n"
        "  <rows>\n    <item>\n      <n>number</n>\n    </item>\n  </rows>\n</dyn>\n"
        "Repeat <item> once for each element of a list."
    )
    assert render_prompt(spec, {"fields": fields})[-1].content == f"go\n\n{text}"


def test_dynamic_schema_uses_the_default_and_checks_the_value() -> None:
    spec = load_prompt(DYNAMIC % "table")
    assert "| name |" in output_instructions(spec)
    with pytest.raises(ValidationError, match="'fields.tags'"):
        output_instructions(spec, {"fields": {"tags": "strin"}})
    with pytest.raises(ValidationError, match="a table has only"):
        output_instructions(spec, {"fields": {"tags": ["string"]}})
    with pytest.raises(ValidationError, match="map of field names"):
        output_instructions(spec, {"fields": ["name"]})
    with pytest.raises(ValidationError, match="one item type"):
        output_instructions(spec, {"fields": {"a": ["string", "number"]}})


def test_dynamic_schema_without_a_value_is_an_error() -> None:
    spec = load_prompt(
        'prompt "p" {\n  variables = { f = map }\n  output { schema = f }\n'
        '  message "user" { text = "x" }\n}\n'
    )
    with pytest.raises(ValidationError, match="has no value"):
        output_instructions(spec)
    with pytest.raises(ValueError, match="Missing required variable"):
        render_prompt(spec, {})


def test_hand_written_format_text_keeps_working() -> None:
    spec = load_prompt('prompt "p" { message "user" { text = "Answer as JSON: {\\"a\\": 1}" } }')
    assert render_prompt(spec, {})[0].content == 'Answer as JSON: {"a": 1}'


# -- the builder --------------------------------------------------------------------------------


@dataclass
class Product:
    name: str
    price: float
    in_stock: bool = True


@dataclass
class Order:
    id: str
    items: list[Product] = field(default_factory=list)


def test_builder_default_format_is_unchanged() -> None:
    builder = BasePromptBuilder()
    builder.set_output_schema("t", Product)
    default = builder.get_output_instructions("t")
    builder.set_output_schema("t", Product, output_format="json")
    assert builder.get_output_instructions("t") == default
    assert default.startswith("Respond with JSON only: an object with these fields:")


def test_builder_table_and_xml() -> None:
    builder = BasePromptBuilder()
    builder.set_output_schema("products", Product, output_format="table")
    assert builder.get_output_instructions("products") == (
        "Answer with a Markdown table and nothing else, one row per item, with these columns:\n"
        "| name | price | in_stock |\n|---|---|---|\n- name: string\n- price: number\n"
        "- in_stock: true or false"
    )
    builder.set_output_schema("Order", Order, output_format="xml")
    assert builder.get_output_instructions("Order") == (
        "Answer with XML only, no text around it, in this shape:\n<order>\n  <id>string</id>\n"
        "  <items>\n    <item>\n      <name>string</name>\n      <price>number</price>\n"
        "      <in_stock>true or false</in_stock>\n    </item>\n  </items>\n</order>\n"
        "Repeat <item> once for each element of a list."
    )
    schema = {"type": "object", "properties": {"label": {"enum": ["a", "b"]}}}
    builder.set_output_schema("d", schema, output_format="table")
    assert builder.get_output_instructions("d").endswith('- label: one of "a", "b"')


def test_builder_rejects_a_bad_format_and_a_nested_table() -> None:
    builder = BasePromptBuilder()
    with pytest.raises(ValidationError, match="json, table, xml or text"):
        builder.set_output_schema("t", Product, output_format="csv")
    with pytest.raises(ValidationError, match="'items'"):
        builder.set_output_schema("t", Order, output_format="table")
    assert builder.get_output_instructions("t") == ""


def test_builder_returns_the_skye_block_instructions() -> None:
    builder = BasePromptBuilder()
    builder.register_template("cat", SMALL % "table")
    assert builder.get_output_instructions("cat") == TABLE_TEXT
    builder.register_template("dyn", DYNAMIC % "json")
    text = builder.get_output_instructions("dyn", {"fields": {"q": "number"}})
    assert '"q"' in text and '"name"' not in text
    assert '"name"' in builder.get_output_instructions("dyn")  # the declared default
    rendered = builder.render("cat", {"text": "x"})
    assert rendered[-1].content == f"Catalogue: x\n\n{TABLE_TEXT}"
    # A schema set explicitly wins over the block.
    builder.set_output_schema("cat", Product)
    assert builder.get_output_instructions("cat").startswith("Respond with JSON only")


# -- filters ------------------------------------------------------------------------------------


def test_toxml_filter() -> None:
    data = {"id": 3, "note": "a<b & c", "lines": [{"sku": "x", "qty": 2}], "ok": True, "no": None}
    assert render_template('{{ order | toxml("order") }}', {"order": data}) == (
        "<order>\n  <id>3</id>\n  <note>a&lt;b &amp; c</note>\n  <lines>\n    <item>\n"
        "      <sku>x</sku>\n      <qty>2</qty>\n    </item>\n  </lines>\n  <ok>true</ok>\n"
        "  <no></no>\n</order>"
    )
    assert render_template("{{ xs | toxml }}", {"xs": [1, 2]}) == (
        "<data>\n  <item>1</item>\n  <item>2</item>\n</data>"
    )


def test_totable_filter() -> None:
    rows = [{"name": "A|1", "price": 2.5}, {"name": "B", "stock": True}]
    assert render_template("{{ rows | totable }}", {"rows": rows}) == (
        "| name | price | stock |\n|---|---|---|\n| A\\|1 | 2.5 |  |\n| B |  | true |"
    )
    assert render_template('{{ rows | totable(["price", "name"]) }}', {"rows": rows}) == (
        "| price | name |\n|---|---|\n| 2.5 | A\\|1 |\n|  | B |"
    )
    assert render_template("{{ row | totable }}", {"row": {"a": 1}}) == "| a |\n|---|\n| 1 |"
    assert render_template("{{ rows | totable }}", {"rows": []}) == ""


def test_filters_work_in_a_skye_prompt() -> None:
    spec = load_prompt(
        'prompt "p" {\n  variables = { rows = list }\n'
        '  message "user" { text = "Data:\\n{{ rows | totable }}" }\n}\n'
    )
    assert render_prompt(spec, {"rows": [{"a": 1}]})[0].content == "Data:\n| a |\n|---|\n| 1 |"


# -- descriptions -------------------------------------------------------------------------------

DESCRIBED = """
prompt "ItemList" {
  output "%s" {
    name     = string    "Product name"
    price    = number(0) "Unit price in EUR"
    in_stock = bool
  }
  message "user" { text = "go" }
}
"""

DESCRIBED_JSON = """Answer with a single JSON object and nothing else.
It must match this JSON Schema:
```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string",
      "description": "Product name"
    },
    "price": {
      "type": "number",
      "description": "Unit price in EUR",
      "default": 0
    },
    "in_stock": {
      "type": "boolean"
    }
  },
  "required": [
    "name",
    "in_stock"
  ]
}
```
Example of the shape:
{"name": "...", "price": 0, "in_stock": false}"""

DESCRIBED_TABLE = """\
Answer with a Markdown table and nothing else, one row per item, with these columns:
| name | price | in_stock |
|---|---|---|
- name: string — Product name
- price: number (default 0) — Unit price in EUR
- in_stock: true or false"""

DESCRIBED_XML = """Answer with XML only, no text around it, in this shape:
<item_list>
  <name>string — Product name</name>
  <price>number (default 0) — Unit price in EUR</price>
  <in_stock>true or false</in_stock>
</item_list>"""


@pytest.mark.parametrize(
    "fmt,expected",
    [("json", DESCRIBED_JSON), ("table", DESCRIBED_TABLE), ("xml", DESCRIBED_XML)],
)
def test_exact_text_of_each_format_with_descriptions(fmt: str, expected: str) -> None:
    assert output_instructions(load_prompt(DESCRIBED % fmt)) == expected


NESTED_DESCRIBED = """
prompt "Invoice" {
  output "%s" {
    vendor = string "Seller name"
    lines  = list({
      amount = number "Amount of the line"
      note   = string
    }) "One entry per line"
    meta   = { source = string "Where the data came from" } "Extra -- data"
  }
  message "user" { text = "go" }
}
"""


def test_nested_descriptions_in_json_and_xml() -> None:
    schema = json.loads(
        output_instructions(load_prompt(NESTED_DESCRIBED % "json"))
        .split("```json\n")[1]
        .split("```")[0]
    )
    lines = schema["properties"]["lines"]
    assert list(lines)[:2] == ["type", "description"]
    assert lines["description"] == "One entry per line"
    assert lines["items"]["properties"]["amount"]["description"] == "Amount of the line"
    assert "description" not in lines["items"]["properties"]["note"]
    assert schema["properties"]["meta"]["properties"]["source"] == {
        "type": "string",
        "description": "Where the data came from",
    }
    assert output_instructions(load_prompt(NESTED_DESCRIBED % "xml")) == (
        "Answer with XML only, no text around it, in this shape:\n<invoice>\n"
        "  <vendor>string — Seller name</vendor>\n"
        "  <lines> <!-- One entry per line -->\n    <item>\n"
        "      <amount>number — Amount of the line</amount>\n      <note>string</note>\n"
        "    </item>\n  </lines>\n"
        "  <meta> <!-- Extra - - data -->\n"
        "    <source>string — Where the data came from</source>\n  </meta>\n</invoice>\n"
        "Repeat <item> once for each element of a list."
    )


def test_dynamic_schema_with_described_fields() -> None:
    spec = load_prompt(DYNAMIC % "xml")
    fields = {
        "a": {"type": "string", "description": "The A"},
        "tags": {"type": "list", "items": "string", "description": "Labels"},
        "rows": {"type": "list", "items": {"n": {"type": "number", "description": "N"}}},
        "sub": {"type": "map", "properties": {"type": "string"}, "description": "Sub"},
        "plain": {"x": "bool"},
    }
    assert output_instructions(spec, {"fields": fields}) == (
        "Answer with XML only, no text around it, in this shape:\n<dyn>\n"
        "  <a>string — The A</a>\n"
        "  <tags> <!-- Labels -->\n    <item>string</item>\n  </tags>\n"
        "  <rows>\n    <item>\n      <n>number — N</n>\n    </item>\n  </rows>\n"
        "  <sub> <!-- Sub -->\n    <type>string</type>\n  </sub>\n"
        "  <plain>\n    <x>true or false</x>\n  </plain>\n</dyn>\n"
        "Repeat <item> once for each element of a list."
    )
    json_spec = load_prompt(DYNAMIC % "json")
    text = output_instructions(json_spec, {"fields": {"t": {"type": "number", "description": "T"}}})
    assert '"t": {\n      "type": "number",\n      "description": "T"\n    }' in text


@pytest.mark.parametrize(
    "value,match",
    [
        ({"type": "strin"}, "unknown type 'strin'"),
        ({"type": "string", "description": ""}, "non-empty string"),
        ({"type": "string", "items": "string"}, '"items" is for a list'),
        ({"type": "list", "properties": {"a": "string"}}, '"properties" is for a map'),
        ({"type": "list", "items": {"type": "string", "description": "x"}}, "describe the list"),
        ([{"type": "string", "description": "x"}], "describe the list"),
    ],
)
def test_dynamic_described_field_mistakes(value: object, match: str) -> None:
    spec = load_prompt(DYNAMIC % "json")
    with pytest.raises(ValidationError, match=match):
        output_instructions(spec, {"fields": {"f": value}})


@dataclass
class Described:
    name: str = field(metadata={"description": "Product name"})
    price: float = field(default=0.0, metadata={"description": "Unit price"})


def test_builder_descriptions_from_dataclass_metadata_and_json_schema() -> None:
    builder = BasePromptBuilder()
    builder.set_output_schema("t", Described, output_format="table")
    assert builder.get_output_instructions("t").endswith(
        "- name: string — Product name\n- price: number — Unit price"
    )
    builder.set_output_schema("t", Described, output_format="xml")
    assert "  <name>string — Product name</name>\n" in builder.get_output_instructions("t")
    builder.set_output_schema("t", Described)
    assert "- name (string, required): Product name" in builder.get_output_instructions("t")
    schema = {
        "type": "object",
        "properties": {"label": {"type": "string", "description": "The class"}},
    }
    builder.set_output_schema("d", schema, output_format="table")
    assert builder.get_output_instructions("d").endswith("- label: string — The class")
    builder.set_output_schema("d", schema)
    assert '"description": "The class"' in builder.get_output_instructions("d")


# -- the format from a variable ------------------------------------------------------------------

FORMAT_FROM = """
prompt "p" {
  variables = { style = string("xml") }
  output style { a = string "The A", tags = list(string) }
  message "user" { text = "go" }
}
"""


def test_the_format_comes_from_a_variable() -> None:
    spec = load_prompt(FORMAT_FROM)
    assert output_instructions(spec).startswith("Answer with XML only")
    assert output_instructions(spec, {"style": "json"}).startswith("Answer with a single JSON")
    assert render_prompt(spec, {"style": "json"})[-1].content.startswith("go\n\nAnswer with a")
    with pytest.raises(ValidationError, match="'csv' is not one of json, table, xml or text"):
        output_instructions(spec, {"style": "csv"})
    with pytest.raises(ValidationError, match="'tags'"):  # a static nested field, checked late
        output_instructions(spec, {"style": "table"})
    no_default = load_prompt(FORMAT_FROM.replace('string("xml")', "string"))
    with pytest.raises(ValidationError, match="output format comes from the variable 'style'"):
        output_instructions(no_default)
