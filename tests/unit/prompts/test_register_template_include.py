"""``register_template`` and the folder loader read ``include``, ``from ... import``, ``use`` and
``override`` from a path (task 26.5)."""

from __future__ import annotations

import pytest

from skye.base.dsl import Resolved
from skye.base.exceptions import ValidationError
from skye.prompts import BasePromptBuilder
from skye.prompts.loaders import load_default_templates

MEMORY = """---
partial = true
---
prompt "memory" {
  variables = {
    show_ids       = bool(false)  "Show item ids"
    persona_memory = list({ id = string("") "Id", content = string "The fact" }, []) "The user"
  }
  message "system" {
    when persona_memory {
      text = "### Persona"
      each m in persona_memory { text = "- {{ m.content }}" }
    }
    when show_ids { text = "Items have ids." }
  }
}
"""

CHAT = """---
version = "1.0"
---
include "lib/memory.skye" as memory

prompt "chat_agent" {
  variables = {
    use memory
    input = string("")  "The user's message"
  }
  message "system" { use memory }
  message "user"   { text = "{{ input }}" }
}
"""

UPKEEP = """include "lib/memory.skye" as memory

prompt "upkeep" {
  variables = {
    use memory
    override show_ids = bool(true)  "Show item ids"
    input = string("")  "The user's message"
  }
  message "system" { use memory }
  message "user"   { text = "{{ input }}" }
}
"""

PLAIN = """prompt "plain" {
  variables = { input = string("") "The user's message" }
  message "user" { text = "{{ input }}" }
}
"""

PERSONA = [{"content": "Likes tea"}]


def _folder(tmp_path):
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "memory.skye").write_text(MEMORY, encoding="utf-8")
    (tmp_path / "chat_agent.skye").write_text(CHAT, encoding="utf-8")
    (tmp_path / "upkeep.skye").write_text(UPKEEP, encoding="utf-8")
    return tmp_path


def _text(builder, name, **variables):
    return "\n".join(str(m.content) for m in builder.render(name, variables))


def test_a_file_with_an_include_registers_from_its_path(tmp_path):
    folder = _folder(tmp_path)
    builder = BasePromptBuilder()
    builder.register_template("chat_agent", str(folder / "chat_agent.skye"), from_string=False)
    out = _text(builder, "chat_agent", input="hi", persona_memory=PERSONA)
    assert "### Persona" in out and "- Likes tea" in out and "Items have ids." not in out
    assert builder.get_template_variables("chat_agent") == ["show_ids", "persona_memory", "input"]


def test_an_override_changes_the_default_of_a_variable_taken_from_a_partial(tmp_path):
    folder = _folder(tmp_path)
    builder = BasePromptBuilder()
    builder.register_template("upkeep", str(folder / "upkeep.skye"), from_string=False)
    assert "Items have ids." in _text(builder, "upkeep", input="hi", persona_memory=PERSONA)


def test_a_text_takes_a_resolver_argument(tmp_path):
    def resolver(target, from_key):
        assert target == "lib/memory.skye"
        return Resolved(text=MEMORY, name=target, key="memory")

    builder = BasePromptBuilder()
    builder.register_template("chat_agent", CHAT, resolver=resolver)
    assert "### Persona" in _text(builder, "chat_agent", input="hi", persona_memory=PERSONA)


def test_a_text_without_a_resolver_cannot_include_and_the_error_names_the_argument():
    builder = BasePromptBuilder()
    with pytest.raises(ValidationError) as caught:
        builder.register_template("chat_agent", CHAT)
    assert "no resolver was given" in caught.value.message and "resolver=" in caught.value.message
    assert "chat_agent" not in builder._latest


def test_a_text_that_starts_with_an_include_is_read_as_skye():
    builder = BasePromptBuilder()
    with pytest.raises(
        ValidationError, match="no resolver was given"
    ):  # not a block template: it is built as .skye
        builder.register_template(
            "x", 'include "a.skye" as a\nprompt "x" { message "user" { text = "t" } }'
        )


def test_a_folder_registers_its_files_with_includes_and_skips_the_partial(tmp_path):
    folder = _folder(tmp_path)
    (folder / "partial_in_folder.skye").write_text(
        MEMORY, encoding="utf-8"
    )  # partial = true, next to the templates
    builder = BasePromptBuilder()
    count = load_default_templates(builder, folder)
    names = {
        n for n in builder._latest if n in {"chat_agent", "upkeep", "memory", "partial_in_folder"}
    }
    assert count == 2 and {"chat_agent", "upkeep"} <= names
    assert "partial_in_folder" not in names and "memory" not in names
    assert "### Persona" in _text(builder, "chat_agent", input="hi", persona_memory=PERSONA)


def test_a_file_without_an_include_registers_as_before(tmp_path):
    path = tmp_path / "plain.skye"
    path.write_text(PLAIN, encoding="utf-8")
    builder = BasePromptBuilder()
    builder.register_template("plain", str(path), from_string=False)
    assert builder._includes == {}  # nothing is kept for a template with no include
    assert _text(builder, "plain", input="hi") == "hi"


def test_a_missing_partial_names_the_folder_searched(tmp_path):
    (tmp_path / "chat_agent.skye").write_text(CHAT, encoding="utf-8")
    builder = BasePromptBuilder()
    with pytest.raises(ValidationError) as caught:
        builder.register_template(
            "chat_agent", str(tmp_path / "chat_agent.skye"), from_string=False
        )
    assert str(tmp_path) in caught.value.message and "lib/memory.skye" in caught.value.message


def test_a_mistake_inside_a_partial_names_its_file_and_the_use_site(tmp_path):
    folder = _folder(tmp_path)
    (folder / "lib" / "memory.skye").write_text(
        MEMORY.replace("when show_ids", "when show_idz"), encoding="utf-8"
    )
    builder = BasePromptBuilder()
    with pytest.raises(ValidationError) as caught:
        builder.register_template("chat_agent", str(folder / "chat_agent.skye"), from_string=False)
    assert "memory.skye" in caught.value.message and "used from" in caught.value.message


def test_registering_again_reads_a_changed_partial(tmp_path):
    folder = _folder(tmp_path)
    builder = BasePromptBuilder()
    path = str(folder / "chat_agent.skye")
    builder.register_template("chat_agent", path, from_string=False)
    (folder / "lib" / "memory.skye").write_text(
        MEMORY.replace("### Persona", "### Who"), encoding="utf-8"
    )
    builder.register_template("chat_agent", path, from_string=False)
    assert "### Who" in _text(builder, "chat_agent", input="hi", persona_memory=PERSONA)


def test_validate_template_rebuilds_a_template_with_includes(tmp_path):
    folder = _folder(tmp_path)
    builder = BasePromptBuilder()
    builder.register_template("chat_agent", str(folder / "chat_agent.skye"), from_string=False)
    assert builder.validate_template("chat_agent")["valid"] is True
