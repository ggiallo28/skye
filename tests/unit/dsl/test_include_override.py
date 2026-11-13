"""The ``override`` of the include (D117): a file changes what a ``use`` brought from a partial."""

from __future__ import annotations

from skye.base.dsl import build
from tests.unit.dsl.include_files import built, plain, reasons

MEMORIES = """---
partial = true
---
prompt "memories" {
  variables = {
    show_ids = bool(false)  "Show the item ids"
    persona_memory = list({
      id      = string("")  "Item id"
      content = string      "What is known"
    }, []) "Who the user and the agent are"
  }
  message "system" {
    when show_ids     { text = "Refer to an item by its id." }
    when not show_ids { text = "Items have no id." }
    when persona_memory { text = "### Persona" }
  }
}
"""
FILES = {"lib/memories.skye": MEMORIES}

WHOLE = """include "lib/memories.skye" as memories

prompt "ids_agent" {
  variables = {
    use memories
    override show_ids = bool(true)  "Ids are shown"
    input = string("")  "The user's message"
  }
  message "system" {
    use memories
    override when not show_ids { text = "Ids are hidden." }
  }
}
"""
WHOLE_BY_HAND = """prompt "ids_agent" {
  variables = {
    show_ids = bool(true)  "Ids are shown"
    persona_memory = list({
      id      = string("")  "Item id"
      content = string      "What is known"
    }, []) "Who the user and the agent are"
    input = string("")  "The user's message"
  }
  message "system" {
    when show_ids     { text = "Refer to an item by its id." }
    when not show_ids { text = "Ids are hidden." }
    when persona_memory { text = "### Persona" }
  }
}
"""
SELECTIVE = """from "lib/memories.skye" import show_ids, persona_memory

prompt "ids_agent" {
  variables = {
    use show_ids
    override show_ids = bool(true)  "Ids are shown"
    use persona_memory
  }
  message "system" {
    use show_ids
    use persona_memory
    override when not show_ids { text = "Ids are hidden." }
  }
}
"""


def prompt_of(text: str):
    document = built(text, FILES)
    assert document.ok, document.diagnostics
    return document.prompt()


def errors(text: str) -> list[str]:
    document = built(text, FILES)
    assert not document.ok
    return reasons(document)


def test_an_override_changes_the_default_a_use_brought_and_the_spec_is_the_hand_written_one():
    expected = build(WHOLE_BY_HAND)
    assert expected.ok, expected.diagnostics
    spec = prompt_of(WHOLE)
    assert plain(spec) == plain(expected.prompt())
    assert spec.variables[0].name == "show_ids" and spec.variables[0].default is True


def test_the_selective_import_form_takes_an_override_too():
    spec = prompt_of(SELECTIVE)
    assert [v.name for v in spec.variables] == ["show_ids", "persona_memory"]
    assert spec.variables[0].default is True


def test_the_overriding_entry_keeps_the_place_of_the_use():
    names = [v.name for v in prompt_of(WHOLE).variables]
    assert names == ["show_ids", "persona_memory", "input"]


def test_an_override_when_replaces_the_block_with_that_exact_condition():
    shown = repr(plain(prompt_of(WHOLE)))
    assert "Ids are hidden." in shown and "Items have no id." not in shown


def test_a_wider_condition_is_replaced_by_its_exact_text_when_the_whole_file_brought_it():
    partial = MEMORIES.replace(
        'when persona_memory { text = "### Persona" }',
        'when persona_memory or show_ids { text = "### Memory" }',
    )
    text = WHOLE.replace(
        "override when not show_ids",
        'override when persona_memory or show_ids { text = "### Mine" }\n'
        "    override when not show_ids",
    )
    document = built(text, {"lib/memories.skye": partial})
    assert document.ok, document.diagnostics
    assert "### Mine" in repr(plain(document.prompt()))
    assert "### Memory" not in repr(plain(document.prompt()))


def test_an_override_before_its_use_is_an_error_that_says_what_was_brought():
    early = WHOLE.replace(
        '    use memories\n    override show_ids = bool(true)  "Ids are shown"',
        '    override show_ids = bool(true)  "Ids are shown"\n    use memories',
    )
    problems = errors(early)
    assert any('cannot override "show_ids"' in p and "brought: none" in p for p in problems)


def test_an_override_of_a_name_that_no_use_brought_lists_the_names_brought():
    problems = errors(WHOLE.replace("override show_ids", "override missing"))
    assert any('cannot override "missing"' in p and "show_ids" in p for p in problems)


def test_an_override_when_without_a_brought_block_lists_the_conditions_brought():
    problems = errors(WHOLE.replace("override when not show_ids", "override when nothing"))
    assert any('cannot override "when nothing"' in p and "when show_ids" in p for p in problems)


def test_the_same_name_cannot_be_overridden_twice():
    twice = WHOLE.replace(
        '    override show_ids = bool(true)  "Ids are shown"',
        '    override show_ids = bool(true)  "Ids are shown"\n'
        '    override show_ids = bool(false)  "Again"',
    )
    assert any('cannot override "show_ids"' in p for p in errors(twice))


def test_a_name_the_file_defines_itself_and_overrides_is_reported_with_both_lines():
    clash = WHOLE.replace(
        "    input = string",
        '    show_ids = bool(false)  "Mine"\n    input = string',
    )
    problems = errors(clash)
    assert any('"show_ids" is defined twice' in p for p in problems)


def test_a_duplicate_without_override_is_still_an_error_naming_both_origins():
    clash = WHOLE.replace('    override show_ids = bool(true)  "Ids are shown"\n', "")
    clash = clash.replace('    override when not show_ids { text = "Ids are hidden." }\n', "")
    clash = clash.replace(
        "    input = string",
        '    show_ids = bool(true)  "Mine"\n    input = string',
    )
    assert any('"show_ids" is defined twice' in p for p in errors(clash))


def test_an_override_in_a_partial_is_refused():
    partial = MEMORIES.replace(
        'show_ids = bool(false)  "Show the item ids"',
        'show_ids = bool(false)  "Show the item ids"\n    override persona_memory = string("")',
    )
    document = built(WHOLE, {"lib/memories.skye": partial})
    assert not document.ok
    assert any("no include, use or override" in d.fix for d in document.diagnostics)


def test_an_override_in_a_file_that_uses_no_partial_is_an_error():
    text = 'prompt "p" {\n  variables = {\n    override a = string("")\n  }\n}\n'
    assert any('cannot override "a"' in p for p in errors(text))


def test_a_variable_called_override_is_still_a_name():
    text = 'prompt "p" {\n  variables = {\n    override = string("")  "A name"\n  }\n}\n'
    document = build(text)
    assert document.ok, document.diagnostics
    assert [v.name for v in document.prompt().variables] == ["override"]
