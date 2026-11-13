"""The ``output`` block of a prompt (D70): build, checks, round trip and JSON Schema."""

from __future__ import annotations

from pathlib import Path

import pytest

from skye.base.dsl import OutputFieldSpec, OutputSpec, block_schema, build, check_text, to_text

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "skye"


def _prompt(body: str, variables: str = "document = string, fields = map, name = string") -> str:
    head = f'prompt "p" {{\n  variables = {{ {variables} }}\n'
    return head + body + '\n  message "user" { text = "hi" }\n}\n'


def _messages(body: str, **kwargs: str) -> list[str]:
    return [d.message for d in check_text(_prompt(body, **kwargs))]


def test_the_former_version_2_fixture_now_builds() -> None:
    doc = build((FIXTURES / "p5.skye").read_text(encoding="utf-8"))
    assert doc.diagnostics == []
    output = doc.prompt().output
    assert output is not None and output.format == "json" and output.schema_from is None
    assert [f.name for f in output.fields] == ["vendor", "total", "currency", "lines"]
    currency, lines = output.fields[2], output.fields[3]
    assert (currency.type, currency.default, currency.required) == ("string", "EUR", False)
    assert (lines.type, lines.item_type) == ("list", "map")
    assert [(f.name, f.type) for f in lines.fields] == [
        ("description", "string"),
        ("amount", "number"),
    ]


def test_every_field_form() -> None:
    doc = build(
        _prompt(
            '  output "xml" { a = string, b = number(1), c = bool, d = list, e = map, '
            "f = list(string), g = [number], h = list({ x = string }), i = map({ y = bool }), "
            "j = { z = string }, k = [{ w = number }] }"
        )
    )
    assert doc.diagnostics == []
    output = doc.prompt().output
    assert output is not None and output.format == "xml"
    shapes = {f.name: (f.type, f.item_type, [g.name for g in f.fields]) for f in output.fields}
    assert shapes == {
        "a": ("string", None, []),
        "b": ("number", None, []),
        "c": ("bool", None, []),
        "d": ("list", None, []),
        "e": ("map", None, []),
        "f": ("list", "string", []),
        "g": ("list", "number", []),
        "h": ("list", "map", ["x"]),
        "i": ("map", None, ["y"]),
        "j": ("map", None, ["z"]),
        "k": ("list", "map", ["w"]),
    }
    assert output.fields[1].default == 1 and not output.fields[1].required


def test_no_label_is_json_and_a_prompt_without_output_has_none() -> None:
    assert build(_prompt("  output { a = string }")).prompt().output == OutputSpec(
        format="json", fields=[OutputFieldSpec(name="a", type="string")]
    )
    assert build(_prompt("")).prompt().output is None


def test_dynamic_schema() -> None:
    output = build(_prompt('  output "table" { schema = fields }')).prompt().output
    assert output == OutputSpec(format="table", schema_from="fields")


def test_an_unknown_format_lists_the_four() -> None:
    (message,) = _messages('  output "csv" { a = string }')
    assert message == 'output format "csv" is not known. Use json, table, xml or text.'
    (message,) = _messages('  output "tabel" { a = string }')
    assert 'Did you mean "table"?' in message and "json, table, xml or text" in message


def test_a_table_with_a_nested_field_names_it() -> None:
    messages = _messages(
        '  output "table" { name = string, tags = list(string), meta = { a = string } }'
    )
    assert len(messages) == 2
    assert messages[0].startswith('output "table": column "tags" is a list;')
    assert messages[1].startswith('output "table": column "meta" is a map;')


def test_an_unknown_type_suggests_the_closest() -> None:
    (message,) = _messages("  output { total = numbr }")
    assert message == 'unknown type "numbr" for "total". Did you mean "number"?'
    (message,) = _messages("  output { lines = list({ amount = strng }) }")
    assert 'unknown type "strng" for "amount". Did you mean "string"?' == message


def test_schema_with_other_fields_is_an_error() -> None:
    (message,) = _messages("  output { schema = fields, extra = string }")
    assert message.startswith('"schema" gives all the fields of the output block')
    assert '"extra"' in message


def test_schema_needs_a_declared_map_variable() -> None:
    (message,) = _messages("  output { schema = feilds }")
    assert (
        message.startswith('variable "feilds" is not declared.')
        and 'Did you mean "fields"?' in message
    )
    (message,) = _messages("  output { schema = name }")
    assert message.startswith('"schema" needs a map variable; "name" is string.')
    (message,) = _messages('  output { schema = "x" }')
    assert message.startswith('"schema" takes the name of a map variable')


def test_at_most_one_output_block() -> None:
    (message,) = _messages("  output { a = string }\n  output { b = string }")
    assert message == 'prompt "p" has more than one output block; keep one'


def test_other_mistakes_in_the_block() -> None:
    assert _messages("  output {}") == ["the output block has no field. Add one: name = string"]
    assert any("set twice" in m for m in _messages("  output { a = string, a = number }"))
    assert any(
        "not allowed in an output block" in m for m in _messages("  output { x { a = string } }")
    )
    assert any(
        "a list type has one item type" in m for m in _messages("  output { a = [string, number] }")
    )
    assert any("the items of a list" in m for m in _messages("  output { a = list(list) }"))
    assert any(
        "is string, the default is a number" in m for m in _messages("  output { a = string(1) }")
    )


def test_an_output_block_in_a_message_is_reported() -> None:
    text = 'prompt "p" {\n  message "user" {\n    text = "hi"\n    output { a = string }\n  }\n}\n'
    (diagnostic,) = check_text(text)
    assert diagnostic.message.startswith("an output block belongs to the prompt, not to a message.")
    assert (diagnostic.line, diagnostic.column) == (4, 5)


def test_an_output_block_at_the_top_of_a_file_is_unknown() -> None:
    (message,) = [d.message for d in check_text("output { a = string }\n")]
    assert message.startswith('unknown block "output".')


@pytest.mark.parametrize(
    "body",
    [
        '  output "json" { vendor = string, total = number, currency = string("EUR"), '
        "lines = list({ description = string, amount = number }), "
        "meta = map({ source = string }) }",
        '  output "table" { name = string, price = number(0), in_stock = bool(true) }',
        '  output "xml" { tags = list(string), any = list, free = map, '
        "deep = { a = { b = [number] } } }",
        '  output "xml" { schema = fields }',
        "  output { a = string }",
    ],
)
def test_round_trip(body: str) -> None:
    spec = build(_prompt(body)).prompt()
    text = to_text(spec)
    assert "output " in text
    again = build(text)
    assert again.diagnostics == []
    assert again.prompt() == spec


def test_the_round_trip_text_of_the_fixture() -> None:
    spec = build((FIXTURES / "p5.skye").read_text(encoding="utf-8")).prompt()
    assert (
        '  output "json" {\n    vendor = string\n    total = number\n    currency = string("EUR")\n'
        "    lines = list({ description = string, amount = number })\n  }\n"
    ) in to_text(spec)


def test_the_block_schema_includes_the_output_block() -> None:
    prompt = block_schema("prompt")
    output = prompt["properties"]["output"]
    text = str(output)
    assert "format" in text and "schema_from" in text and "fields" in text
    assert "'json', 'table', 'xml'" in text


# -- descriptions: the string after the type -----------------------------------------------------

DESCRIBED = """  output "json" {
    vendor   = string          "Seller name as printed on the invoice"
    total    = number          "Total amount including VAT"
    currency = string("EUR")   "ISO 4217 currency code"
    tags     = list(string)    "Free labels"
    lines    = list({
      description = string    "Text of the line"
      amount      = number    "Amount of the line"
    })                         "One entry per invoice line"
    meta     = { source = string "Where the data came from" }   "Extra data"
    plain    = bool
  }"""


def test_descriptions_are_read_at_every_level() -> None:
    doc = build(_prompt(DESCRIBED))
    assert doc.diagnostics == []
    output = doc.prompt().output
    assert output is not None
    notes = {f.name: f.description for f in output.fields}
    assert notes == {
        "vendor": "Seller name as printed on the invoice",
        "total": "Total amount including VAT",
        "currency": "ISO 4217 currency code",
        "tags": "Free labels",
        "lines": "One entry per invoice line",
        "meta": "Extra data",
        "plain": None,
    }
    currency, lines, meta = output.fields[2], output.fields[4], output.fields[5]
    assert (currency.default, currency.required) == ("EUR", False)
    assert [(f.name, f.description) for f in lines.fields] == [
        ("description", "Text of the line"),
        ("amount", "Amount of the line"),
    ]
    assert [(f.name, f.description) for f in meta.fields] == [
        ("source", "Where the data came from")
    ]


def test_descriptions_in_the_comma_form() -> None:
    output = (
        build(
            _prompt(
                '  output "xml" { a = string "x", b = number, '
                'c = map({ d = bool "y", e = number }) "z", f = [{ g = string "w" }] "v" }'
            )
        )
        .prompt()
        .output
    )
    assert output is not None
    assert [(f.name, f.description) for f in output.fields] == [
        ("a", "x"),
        ("b", None),
        ("c", "z"),
        ("f", "v"),
    ]
    assert [(f.name, f.description) for f in output.fields[2].fields] == [("d", "y"), ("e", None)]
    assert output.fields[3].fields[0].description == "w"


def test_a_description_outside_an_output_block_is_an_error() -> None:
    # a prompt variable takes a description (test_variable_descriptions.py); a flow field does not
    assert check_text(
        'flow "f" {\n  context { a = string "x" }\n  step "s" { run = registry.x }\n}\n'
    )
    assert check_text('prompt "p" {\n  message "user" { text = "hi" "there" }\n}\n')


def test_description_mistakes() -> None:
    (message,) = _messages('  output { a = string "" }')
    assert message.startswith('the description of "a" is empty.')
    (message,) = _messages('  output { schema = fields "the fields" }')
    assert message.startswith('"schema" takes no description')
    assert check_text(_prompt('  output { a = string "x" "y" }'))
    assert check_text(_prompt('  output { a = [string "x"] }'))


def test_round_trip_with_descriptions() -> None:
    spec = build(_prompt(DESCRIBED)).prompt()
    text = to_text(spec)
    assert (
        '  output "json" {\n'
        '    vendor = string "Seller name as printed on the invoice"\n'
        '    total = number "Total amount including VAT"\n'
        '    currency = string("EUR") "ISO 4217 currency code"\n'
        '    tags = list(string) "Free labels"\n'
        "    lines = list({\n"
        '      description = string "Text of the line"\n'
        '      amount = number "Amount of the line"\n'
        '    }) "One entry per invoice line"\n'
        "    meta = map({\n"
        '      source = string "Where the data came from"\n'
        '    }) "Extra data"\n'
        "    plain = bool\n"
        "  }\n"
    ) in text
    again = build(text)
    assert again.diagnostics == []
    assert again.prompt() == spec


def test_round_trip_of_a_description_only_inside_a_nested_map() -> None:
    spec = build(
        _prompt('  output { a = string, m = { b = { c = number "deep \\"q\\"\\nline" } } }')
    ).prompt()
    text = to_text(spec)
    assert build(text).prompt() == spec
    assert 'c = number "deep \\"q\\"\\nline"' in text


def test_the_block_schema_has_the_description() -> None:
    assert "description" in str(block_schema("prompt")["properties"]["output"])


# -- the format from a variable: output VAR { ... } ----------------------------------------------


def test_the_format_from_a_string_variable() -> None:
    body = "  output style { schema = fields }"
    output = build(_prompt(body, variables='style = string("table"), fields = map')).prompt().output
    assert output == OutputSpec(format="json", format_from="style", schema_from="fields")
    output = build(_prompt("  output style { a = list(string) }", variables="style = string"))
    assert output.diagnostics == []  # a table check waits for the value
    spec = output.prompt()
    assert spec.output is not None and spec.output.format_from == "style"
    text = to_text(spec)
    assert "  output style { a = list(string) }\n" in text
    assert build(text).prompt() == spec


def test_format_variable_mistakes() -> None:
    variables = 'style = string, n = number, bad = string("csv")'
    (message,) = _messages("  output styel { a = string }", variables=variables)
    assert message.startswith('variable "styel" is not declared; it cannot give the output format.')
    assert 'Did you mean "style"?' in message
    (message,) = _messages("  output json { a = string }", variables=variables)
    assert message.endswith('Write the format as a string: output "json" { ... }')
    (message,) = _messages("  output n { a = string }", variables=variables)
    assert message.startswith('the output format comes from "n", which is number; it must be')
    (message,) = _messages("  output bad { a = string }", variables=variables)
    assert (
        message
        == 'the default of "bad" is "csv", which is not an output format. Use json, table, xml or text.'
    )


def test_the_block_schema_has_format_from() -> None:
    assert "format_from" in str(block_schema("prompt")["properties"]["output"])
