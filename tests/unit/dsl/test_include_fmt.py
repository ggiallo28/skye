"""Requirement 63: ``skye fmt`` keeps ``include``, ``from ... import`` and ``use`` where they are (task 25.3)."""

from __future__ import annotations

import pytest

from skye.base.dsl.fmt import FormatError, format_text
from tests.unit.dsl.include_files import AGENT, CHAT_AGENT, MEMORY, TOOL_AGENT

UNFORMATTED = """include "lib/memory.skye" as memory
from "lib/agent.skye"   import system_prompt,   tools
prompt "x" {
variables = {
use system_prompt
   use memory
  input = string("")  "The user's message"
}
  message "system" {
  use system_prompt
 when persona_memory { use persona_memory }
}
}
"""


def test_the_include_lines_and_the_use_lines_stay_where_they_are() -> None:
    result = format_text(UNFORMATTED, "x.skye")
    lines = [line.strip() for line in result.splitlines()]
    assert lines[:2] == ['include "lib/memory.skye" as memory', 'from "lib/agent.skye"   import system_prompt,   tools']
    assert lines.index("use system_prompt") < lines.index("use memory") < lines.index('input = string("")  "The user\'s message"')
    assert "    use memory" in result  # indented as the entries around it


def test_formatting_twice_gives_the_same_text() -> None:
    once = format_text(UNFORMATTED, "x.skye")
    assert format_text(once, "x.skye") == once


@pytest.mark.parametrize("text", [TOOL_AGENT, CHAT_AGENT])
def test_the_files_of_the_design_are_already_formatted(text: str) -> None:
    assert format_text(text, "app.skye") == text


@pytest.mark.parametrize("text", [AGENT, MEMORY])
def test_a_partial_is_formatted_with_its_front_matter_untouched(text: str) -> None:
    result = format_text(text.replace("\n  ", "\n      ", 6), "lib.skye")
    assert result.startswith("---\npartial = true\n---\n")
    assert format_text(result, "lib.skye") == result


def test_a_syntax_mistake_is_still_refused() -> None:
    with pytest.raises(FormatError, match="mistakes"):
        format_text('prompt "x" {\n  message "system" { use }\n', "x.skye")


def test_a_file_without_include_is_formatted_as_before() -> None:
    text = 'prompt "p" {\n message "system" {  text = "hi" }\n}\n'
    assert format_text(text, "p.skye") == 'prompt "p" {\n  message "system" {  text = "hi" }\n}\n'


def test_to_text_writes_the_expanded_prompt_and_no_use() -> None:
    from skye.base.dsl import to_text
    from tests.unit.dsl.include_files import FILES, TOOL_AGENT, built

    written = to_text(built(TOOL_AGENT, FILES))
    statements = [l for l in written.splitlines() if l.strip().startswith(("use ", "include ", "from "))]
    assert statements == []  # the words may appear inside the text of a message, never as a statement
    assert "persona_memory" in written and "when tools" in written
