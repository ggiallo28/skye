"""Requirement 63: the file system resolver of ``include`` and what loads through it (task 25.3)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import skye
from skye.base.exceptions import ConfigurationError
from skye.utils.skye_files import clear_files_cache, file_resolver, load_document
from tests.unit.dsl.include_files import CHAT_AGENT, FILES, TOOL_AGENT


@pytest.fixture
def project(tmp_path: Path) -> Path:
    for name, text in FILES.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    (tmp_path / "tool_agent.skye").write_text(TOOL_AGENT, encoding="utf-8")
    (tmp_path / "chat_agent.skye").write_text(CHAT_AGENT, encoding="utf-8")
    clear_files_cache()
    return tmp_path


def test_a_target_is_read_relative_to_the_entry_folder(project: Path) -> None:
    resolve = file_resolver(project / "tool_agent.skye")
    found = resolve("lib/agent.skye", str((project / "tool_agent.skye").resolve()))
    assert found.name == "lib/agent.skye"
    assert found.key == str((project / "lib" / "agent.skye").resolve())
    assert found.text.startswith("---\npartial = true")


def test_dot_dot_is_allowed_while_it_stays_inside_the_root(project: Path) -> None:
    resolve = file_resolver(project / "tool_agent.skye")
    assert resolve("lib/../lib/agent.skye", None).name == "lib/agent.skye"


def test_a_target_that_leaves_the_root_is_an_error(project: Path, tmp_path: Path) -> None:
    outside = project.parent / "outside.skye"
    outside.write_text("x", encoding="utf-8")
    resolve = file_resolver(project / "tool_agent.skye")
    with pytest.raises(ValueError, match="outside"):
        resolve("../outside.skye", None)


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="no symbolic links")
def test_a_symbolic_link_whose_real_path_leaves_the_root_is_an_error(project: Path) -> None:
    outside = project.parent / "secret.skye"
    outside.write_text("x", encoding="utf-8")
    (project / "lib" / "link.skye").symlink_to(outside)
    with pytest.raises(ValueError, match="outside"):
        file_resolver(project / "tool_agent.skye")("lib/link.skye", None)


def test_a_missing_file_names_the_folder_searched(project: Path) -> None:
    resolve = file_resolver(project / "tool_agent.skye")
    with pytest.raises(FileNotFoundError, match=str(project.resolve())):
        resolve("lib/none.skye", str((project / "tool_agent.skye").resolve()))


def test_load_reads_the_includes_of_a_file(project: Path) -> None:
    document = skye.load(project / "tool_agent.skye")
    names = [v.name for v in document.prompt("tool_agent").variables]
    assert names[:2] == ["system_prompt", "tools"]
    assert "persona_memory" in names


def test_load_reports_a_missing_partial_at_the_include_line(project: Path) -> None:
    (project / "lib" / "memory.skye").unlink()
    with pytest.raises(ConfigurationError) as caught:
        skye.load(project / "tool_agent.skye")
    message = str(caught.value)
    assert "tool_agent.skye:2" in message and "lib/memory.skye" in message
    assert str(project.resolve()) in message  # the folder searched


def test_a_changed_partial_is_never_served_from_the_cache(project: Path) -> None:
    first = load_document(project / "chat_agent.skye")
    assert not first.diagnostics
    memory = project / "lib" / "memory.skye"
    memory.write_text(
        memory.read_text(encoding="utf-8").replace("Who the user and the agent are", "Changed"),
        encoding="utf-8",
    )
    second = load_document(project / "chat_agent.skye")
    assert second.prompt("chat_agent").variables[0].description == "Changed"
    assert first.prompt("chat_agent").variables[0].description != "Changed"


def test_a_file_without_include_keeps_using_the_cache(project: Path) -> None:
    plain_file = project / "plain.skye"
    plain_file.write_text('prompt "p" {\n  message "system" { text = "hi" }\n}\n', encoding="utf-8")
    assert load_document(plain_file) is load_document(plain_file)
