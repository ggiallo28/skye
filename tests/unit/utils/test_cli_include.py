"""``skye check``, ``fmt``, ``prompt list`` and ``prompt info`` on files that use ``include`` (task 25.3, Requirement 63)."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from skye.prompts import loaders
from skye.utils.cli import main
from tests.unit.dsl.include_files import AGENT, CHAT_AGENT, MEMORY, TOOL_AGENT


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "agent.skye").write_text(AGENT, encoding="utf-8")
    (tmp_path / "lib" / "memory.skye").write_text(MEMORY, encoding="utf-8")
    (tmp_path / "tool_agent.skye").write_text(TOOL_AGENT, encoding="utf-8")
    (tmp_path / "chat_agent.skye").write_text(CHAT_AGENT, encoding="utf-8")
    return tmp_path


def test_check_resolves_the_includes_of_a_file(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["check", str(project / "tool_agent.skye"), str(project / "chat_agent.skye")]) == 0
    assert capsys.readouterr().out.count(": ok") == 2


def test_check_says_that_a_partial_is_checked_where_it_is_used(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["check", str(project / "lib" / "memory.skye")]) == 0
    assert "a partial" in capsys.readouterr().out


def test_check_reports_a_missing_partial_with_the_folder_searched(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (project / "lib" / "agent.skye").unlink()
    assert main(["check", str(project / "tool_agent.skye")]) == 1
    out = capsys.readouterr().out
    assert "lib/agent.skye" in out and str(project.resolve()) in out


def test_check_on_stdin_with_a_filename_reads_the_includes_there(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(TOOL_AGENT.encode())))
    code = main(["check", "--format", "json", "--stdin-filename", str(project / "tool_agent.skye"), "-"])
    assert code == 0 and json.loads(capsys.readouterr().out) == {"diagnostics": []}


def test_check_on_stdin_without_a_filename_asks_for_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(TOOL_AGENT.encode())))
    assert main(["check", "-"]) == 1
    assert "--stdin-filename" in capsys.readouterr().out


def test_check_json_carries_via_for_a_mistake_in_a_partial(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (project / "lib" / "memory.skye").write_text(MEMORY.replace('each m in persona_memory', 'each m in nothing_here'), encoding="utf-8")
    code = main(["check", "--format", "json", str(project / "tool_agent.skye")])
    found = json.loads(capsys.readouterr().out)["diagnostics"]
    assert code == 1 and found and found[0]["via"][0]["file"].endswith("tool_agent.skye")


def test_fmt_formats_a_file_with_includes_and_a_partial(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    messy = project / "messy.skye"
    messy.write_text(CHAT_AGENT.replace("\n  ", "\n      "), encoding="utf-8")
    partial = project / "lib" / "memory.skye"
    partial.write_text(MEMORY.replace("\n    ", "\n        "), encoding="utf-8")
    assert main(["fmt", "--check", str(messy), str(partial)]) == 1
    assert main(["fmt", str(messy), str(partial)]) == 0
    assert messy.read_text(encoding="utf-8") == CHAT_AGENT
    assert partial.read_text(encoding="utf-8") == MEMORY.replace("---\nprompt", "---\n\nprompt")  # one blank line after the front matter
    assert main(["fmt", str(project)]) == 0  # the whole folder, partials included
    assert main(["fmt", "--check", str(project)]) == 0


def test_prompt_info_reads_the_includes_of_a_file(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["prompt", "info", str(project / "chat_agent.skye")]) == 0
    assert "persona_memory" in capsys.readouterr().out


def test_prompt_list_skips_a_partial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    folder = tmp_path / "templates"
    folder.mkdir()
    (folder / "chat.skye").write_text('---\ntitle = "Chat"\nversion = "1.0"\n---\nprompt "chat" {\n  message "system" { text = "hi" }\n}\n', encoding="utf-8")
    (folder / "memory.skye").write_text(MEMORY, encoding="utf-8")
    monkeypatch.setattr(loaders, "TEMPLATES_DIR", folder)
    monkeypatch.setattr(loaders, "_archive_index", None)
    assert main(["prompt", "list"]) == 0
    out = capsys.readouterr().out
    assert "chat" in out and "memory" not in out


def test_render_of_a_flow_is_not_affected_by_a_prompt_with_includes_next_to_it(project: Path) -> None:
    flow = project / "app.skye"
    flow.write_text('flow "one" { step "a" { run = registry.a, next = end } }\n', encoding="utf-8")
    assert main(["render", str(flow)]) == 0
    assert (project / "app.mmd").read_text(encoding="utf-8").startswith("flowchart TD\n")
