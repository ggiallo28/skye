"""The ``text`` format of the ``output`` block: a plain answer, with an optional style."""

from __future__ import annotations

import pytest

from skye.base.dsl import build, check_text, format_text, to_text
from skye.base.exceptions import ValidationError
from skye.prompts import BasePromptBuilder, load_prompt, output_instructions, render_prompt

PLAIN = "Answer in plain text, with no JSON, table or markup around it."


def _prompt(output: str, variables: str = "q = string") -> str:
    head = f'prompt "p" {{\n  variables = {{ {variables} }}\n  {output}\n'
    return head + '  message "user" { text = "{{ q }}" }\n}\n'


def _spec(output: str, variables: str = "q = string"):
    return load_prompt(_prompt(output, variables))


def test_the_text_format_with_no_line_builds_and_asks_for_plain_text() -> None:
    doc = build(_prompt('output "text" {}'))
    assert doc.diagnostics == []
    out = doc.prompt().output
    assert out is not None and (out.format, out.style, out.style_from) == ("text", None, None)
    assert output_instructions(doc.prompt()) == PLAIN


def test_a_literal_style_is_added_to_the_instruction() -> None:
    spec = _spec('output "text" { style = "a short paragraph" }')
    assert spec.output is not None and spec.output.style == "a short paragraph"
    assert output_instructions(spec) == "Answer in plain text: a short paragraph."


def test_a_style_can_come_from_a_string_variable() -> None:
    spec = _spec(
        'output "text" { style = how }', variables='q = string, how = string("a bulleted list")'
    )
    assert spec.output is not None and spec.output.style_from == "how"
    assert output_instructions(spec) == "Answer in plain text: a bulleted list."
    assert output_instructions(spec, {"how": "one sentence"}) == (
        "Answer in plain text: one sentence."
    )
    assert output_instructions(spec, {"how": ""}) == PLAIN


def test_the_instruction_is_the_last_text_of_the_user_message() -> None:
    spec = _spec('output "text" { style = "a short paragraph" }')
    messages = render_prompt(spec, {"q": "Hello"})
    assert messages[-1].content == "Hello\n\nAnswer in plain text: a short paragraph."


def test_a_conditional_text_output_next_to_a_json_one() -> None:
    text = (
        'prompt "p" {\n  variables = { q = string, fmt = string("text") }\n'
        '  when fmt == "text" { output "text" { style = "two lines" } }\n'
        '  when fmt == "json" { output "json" { answer = string } }\n'
        '  message "user" { text = "{{ q }}" }\n}\n'
    )
    spec = load_prompt(text)
    assert output_instructions(spec) == "Answer in plain text: two lines."
    assert output_instructions(spec, {"fmt": "json"}).startswith("Answer with a single JSON")


def test_a_format_variable_whose_value_is_text_ignores_the_fields() -> None:
    spec = _spec("output fmt { answer = string }", variables='q = string, fmt = string("json")')
    assert output_instructions(spec).startswith("Answer with a single JSON")
    assert output_instructions(spec, {"fmt": "text"}) == PLAIN
    spec = _spec(
        "output fmt { schema = fields }",
        variables='q = string, fmt = string("text"), fields = map({})',
    )
    assert output_instructions(spec) == PLAIN


def test_a_field_in_a_text_output_is_an_error_that_says_so() -> None:
    (diagnostic,) = check_text(_prompt('output "text" { name = string }'))
    assert (
        diagnostic.reason == 'output "text": "name" is not allowed; a plain answer has no fields.'
    )
    assert "style" in diagnostic.fix


def test_a_style_that_is_not_a_string_or_a_declared_string_variable_is_an_error() -> None:
    assert check_text(_prompt('output "text" { style = nope }'))
    assert check_text(_prompt('output "text" { style = 3 }'))
    assert check_text(
        _prompt('output "text" { style = how }', variables="q = string, how = number")
    )


def test_the_unknown_format_error_lists_the_four() -> None:
    (diagnostic,) = check_text(_prompt('output "plain" { name = string }'))
    assert "Use json, table, xml or text." in diagnostic.fix


def test_a_bare_text_label_is_the_variable_form() -> None:
    (diagnostic,) = check_text(_prompt("output text {}"))
    assert 'output "text"' in diagnostic.fix


def test_a_default_that_is_not_a_format_is_still_an_error() -> None:
    body = "output fmt { answer = string }"
    assert check_text(_prompt(body, variables='q = string, fmt = string("plain")'))
    assert not check_text(_prompt(body, variables='q = string, fmt = string("text")'))


@pytest.mark.parametrize(
    "line",
    [
        'output "text" {}',
        'output "text" { style = "a short paragraph" }',
        'output "text" { style = how }',
    ],
)
def test_round_trip_through_to_text_and_fmt(line: str) -> None:
    variables = 'q = string, how = string("one line")'
    text = _prompt(line, variables)
    doc = build(text)
    assert doc.diagnostics == []
    again = build(to_text(doc))
    assert again.diagnostics == [] and again.prompt().output == doc.prompt().output
    formatted = format_text(text)
    assert format_text(formatted) == formatted
    assert build(formatted).prompt().output == doc.prompt().output


def test_prompt_info_says_plain_text() -> None:
    from skye.base.dsl.info import describe_prompt

    info = describe_prompt(build(_prompt('output "text" {}')).prompt())
    assert info.output is not None and info.output.format == "text"


def test_set_output_schema_refuses_text() -> None:
    builder = BasePromptBuilder()
    builder.register_template("t", "Hello {{ name }}")
    with pytest.raises(ValidationError, match="has no fields"):
        builder.set_output_schema("t", {"type": "object", "properties": {}}, output_format="text")
