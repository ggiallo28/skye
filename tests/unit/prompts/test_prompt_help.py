"""Prompt help: describe_prompt, prompt_help and BasePromptBuilder.describe / help."""

from __future__ import annotations

import pytest

from skye.base.dsl import build
from skye.prompts import (
    BasePromptBuilder,
    InputInfo,
    OutputInfo,
    PromptInfo,
    describe_prompt,
    prompt_help,
)
from tests.unit.prompts.bundled import gallery_builder

TEXT = """---
title = "Invoice extractor"
description = "Reads an invoice and returns its lines."
version = "2.1"
tags = ["extraction"]
---

prompt "invoice" {
  variables = {
    document = string "The invoice text"
    currency = string("EUR") "Currency of the amounts"
    notes = list
    turns = list([])
  }
  allow_missing = ["notes"]

  message "system" { text = "You extract invoices." }
  when notes {
    message "system" { text = "Notes: {{ notes | join(', ') }}" }
  }
  placeholder "history"
  each turn in turns {
    message turn.role { text = "{{ turn.content }}" }
  }
  message "user" { text = "{{ document }} in {{ currency }}" }

  output "json" {
    total = number "Total amount"
    lines = list({
      amount = number "Amount of the line"
      label = string
    })
    paid = bool(false)
  }
}
"""

EXPECTED = """invoice — Invoice extractor (2.1)
Reads an invoice and returns its lines.
Tags: extraction

Inputs
  document  string  required  The invoice text
  currency  string  = "EUR"   Currency of the amounts
  notes     list    optional
  turns     list    = []

History
  history

Messages
  system, system?, history, turn.role*, user

Output (json)
  total     number       required  Total amount
  lines     list of map  required
    amount  number       required  Amount of the line
    label   string       required
  paid      bool         = false
"""


def test_prompt_help_text() -> None:
    document = build(TEXT).raise_for_errors()
    assert prompt_help(document.prompt(), document.metadata) == EXPECTED


def test_describe_prompt() -> None:
    document = build(TEXT).raise_for_errors()
    info = describe_prompt(document.prompt(), document.metadata)
    assert isinstance(info, PromptInfo)
    assert (info.name, info.title, info.version, info.tags) == (
        "invoice",
        "Invoice extractor",
        "2.1",
        ["extraction"],
    )
    assert info.description == "Reads an invoice and returns its lines."
    assert info.inputs[0] == InputInfo(
        name="document", type="string", required=True, description="The invoice text"
    )
    notes = info.inputs[2]
    assert (notes.required, notes.allow_missing, notes.default) == (False, True, None)
    assert info.placeholders == ["history"]
    assert info.roles == ["system", "system?", "history", "turn.role*", "user"]
    assert isinstance(info.output, OutputInfo)
    assert info.output.format == "json"
    lines = info.output.fields[1]
    assert (lines.type, lines.item_type) == ("list", "map")
    assert [f.name for f in lines.fields] == ["amount", "label"]
    assert info.output.fields[2].default is False


def test_without_metadata_or_output() -> None:
    spec = build('prompt "p" {\n  message "user" { text = "hi" }\n}\n').raise_for_errors().prompt()
    assert prompt_help(spec) == (
        "p\n\nInputs\n  (none)\n\nHistory\n  (none)\n\nMessages\n  user\n\nOutput\n  free text\n"
    )
    assert describe_prompt(spec).output is None


def test_output_from_variables() -> None:
    text = (
        'prompt "p" {\n  variables = { fmt = string("json"), fields = map }\n'
        '  message "user" { text = "hi" }\n  output fmt { schema = fields }\n}\n'
    )
    info = describe_prompt(build(text).raise_for_errors().prompt())
    assert info.output == OutputInfo(format="from variable fmt", fields_from="fields")
    assert prompt_help(info).endswith("Output (from variable fmt)\n  fields from variable fields\n")


def test_builder_help_of_a_prompt_registered_from_a_file() -> None:
    builder = gallery_builder()
    text = builder.help("agent_planner")
    assert text.startswith("agent_planner — ")
    assert "\nInputs\n" in text and "  task " in text
    info = builder.describe("agent_planner")
    assert info.version == "1.0"
    assert "history" in info.placeholders


def test_builder_help_of_a_skye_string() -> None:
    builder = BasePromptBuilder()
    builder.register_template("invoice", TEXT, version="2.1")
    assert builder.help("invoice") == EXPECTED


def test_builder_describe_of_a_text_template() -> None:
    builder = BasePromptBuilder()
    builder.register_template(
        "t", "[SYSTEM]\nBe {{ tone }}\n[PLACEHOLDER past]\n[USER]\n{{ q }}", version="3"
    )
    builder.set_default_values({"tone": "brief"})
    builder.set_output_schema(
        "t",
        {
            "type": "object",
            "properties": {
                "a": {"type": "string", "description": "x"},
                "b": {"type": "array", "items": {"type": "integer"}},
            },
            "required": ["a"],
        },
        output_format="xml",
    )
    info = builder.describe("t")
    assert info.version == "3"
    assert [(i.name, i.type, i.required, i.default) for i in info.inputs] == [
        ("tone", "any", False, "brief"),
        ("q", "any", True, None),
    ]
    assert info.roles == ["system", "past", "user"]
    assert info.placeholders == ["past"]
    assert builder.help("t").endswith(
        "Output (xml)\n  a  string          required  x\n  b  list of number  optional\n"
    )


def test_builder_describe_without_markers() -> None:
    builder = BasePromptBuilder()
    builder.register_template("s", "Hello {name}")
    builder.add_message_placeholder("s", "history")
    info = builder.describe("s")
    assert info.roles == ["history", "user"]
    assert info.output is None


def test_unknown_template() -> None:
    with pytest.raises(KeyError):
        BasePromptBuilder().help("nope")
