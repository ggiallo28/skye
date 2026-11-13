"""The bundled ``extraction_generic`` prompt (task 24.13).

It replaces the four extraction prompts and the classification one. An extraction of entities, of
relations, of a table, of structured data with the default fields and a classification are five
cases of the same prompt: the ``schema`` fields and the allowed ``labels`` say what to extract or
decide, ``format`` how to write it. The five cases are the renders of
``examples/prompts/bundled/extraction_generic.json``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from skye.base.messages import AssistantMessage, SystemMessage, UserMessage
from skye.prompts import BasePromptBuilder

SAMPLES = (
    Path(__file__).resolve().parents[3]
    / "examples"
    / "prompts"
    / "bundled"
    / "extraction_generic.json"
)
NAME = "extraction_generic"
CASES = {
    case["_case"]: {k: v for k, v in case.items() if k != "_case"}
    for case in json.loads(SAMPLES.read_text("utf-8"))
}


def _render(variables: dict[str, Any]):
    return BasePromptBuilder().render(NAME, variables)


def _text(message: Any) -> str:
    assert isinstance(message.content, str)
    return message.content


def test_the_sample_file_has_the_five_cases() -> None:
    assert list(CASES) == ["entities", "relations", "table", "default fields", "classification"]


@pytest.mark.parametrize("case", list(CASES))
def test_every_case_renders_the_rules_once_and_a_precise_system_sentence(case: str) -> None:
    messages = _render(CASES[case])
    system = messages[0]
    assert isinstance(system, SystemMessage)
    assert "precise data extractor" in _text(system)
    assert _text(system).count("never invent") == 1
    assert isinstance(messages[-1], UserMessage)


def test_the_entities_case_lists_the_labels_once_with_their_descriptions() -> None:
    messages = _render(CASES["entities"])
    system = _text(messages[0])
    assert system.count("## Allowed types") == 1
    for name, description in (
        ("PERSON", "Names of people"),
        ("ORG", "Organizations"),
        ("LOC", "Places"),
    ):
        assert f"- **{name}**: {description}" in system
    assert "Use only these; do not invent others." in system
    last = _text(messages[-1])
    assert "Tim Cook presented the new iPhone in Cupertino." in last
    assert '"entities"' in last  # the field of the schema, in the generated JSON instructions


def test_the_relations_case_names_the_relation_types_and_asks_for_subject_relation_object() -> None:
    messages = _render(CASES["relations"])
    assert "- **WORKS_WITH**" in _text(messages[0]) and "- **LOCATED_IN**" in _text(messages[0])
    last = _text(messages[-1])
    for field in ("subject", "relation", "object"):
        assert f'"{field}"' in last


def test_the_table_case_asks_for_a_table_and_sends_its_examples_as_turns() -> None:
    messages = _render(CASES["table"])
    roles = [type(message) for message in messages]
    assert roles == [SystemMessage, UserMessage, AssistantMessage, UserMessage]
    assert "| name | price | in_stock |" in _text(
        messages[2]
    )  # the example answer, as an assistant turn
    last = _text(messages[-1])
    assert "## Task" in last and "List every product with its price" in last and "## Input" in last
    assert "table" in last.lower() and "price: number" in last


def test_the_default_fields_case_asks_for_a_name_and_a_value() -> None:
    last = _text(_render(CASES["default fields"])[-1])
    assert '"name"' in last and '"value"' in last
    assert "Pens 1.20 EUR, ink 3 EUR." in last


def test_the_classification_case_lists_the_categories_once_and_asks_for_its_fields() -> None:
    messages = _render(CASES["classification"])
    system = _text(messages[0])
    assert system.count("## Allowed types") == 1
    assert "- **complaint**: The customer reports a problem" in system
    assert "- **praise**: The customer is satisfied" in system
    assert "- **question**: The customer asks for information" in system
    assert "Classify the text into exactly one of the labels." in system
    assert "always holds one of them" in system  # a field of an allowed type is never left empty
    assert "Messages from the customer support inbox of an online shop." in system
    last = _text(messages[-1])
    for field in ("category", "confidence", "reasoning"):
        assert f'"{field}"' in last
    assert [type(m) for m in messages[1:-1]] == [
        UserMessage,
        AssistantMessage,
        UserMessage,
        AssistantMessage,
    ]


@pytest.mark.parametrize(
    ("fmt", "needle"),
    [("json", "JSON object"), ("table", "table"), ("xml", "XML"), ("text", "plain text")],
)
def test_every_format_gives_its_own_instructions(fmt: str, needle: str) -> None:
    variables = {
        "input": "Pens, 1.20 EUR.",
        "schema": {"name": "string", "price": "number"},
        "format": fmt,
    }
    assert needle.lower() in _text(_render(variables)[-1]).lower()


def test_a_system_prompt_replaces_the_default_sentence() -> None:
    messages = _render({"input": "x", "system_prompt": "You are a terse extractor."})
    system = _text(messages[0])
    assert (
        system.startswith("You are a terse extractor.") and "precise data extractor" not in system
    )
    assert "## Rules" in system  # the rules stay


def test_a_label_can_carry_example_mentions() -> None:
    labels = [
        {"name": "WORKS_FOR", "description": "Employment", "examples": ["joined", "works at"]}
    ]
    system = _text(_render({"input": "x", "labels": labels})[0])
    assert "Examples: joined, works at" in system


def test_instructions_constraints_and_context_are_sections_of_the_system_message() -> None:
    variables = {
        "input": "x",
        "instructions": ["Write prices without the currency symbol."],
        "constraints": ["At most ten rows."],
        "context": "Invoices of a stationery shop.",
    }
    system = _text(_render(variables)[0])
    for part in (
        "## Instructions",
        "- Write prices without the currency symbol.",
        "## Constraints",
        "- At most ten rows.",
        "## Context",
        "Invoices of a stationery shop.",
    ):
        assert part in system
