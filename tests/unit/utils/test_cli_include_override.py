"""``skye check``, ``fmt`` and ``prompt list`` on files that use ``override`` (task 26.2,
Requirement 63.21)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from skye.prompts import loaders
from skye.utils.cli import main
from tests.unit.dsl.test_include_override import MEMORIES, WHOLE


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "memories.skye").write_text(MEMORIES, encoding="utf-8")
    (tmp_path / "ids_agent.skye").write_text(WHOLE, encoding="utf-8")
    return tmp_path


def test_check_accepts_a_file_that_overrides_what_a_partial_brings(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["check", str(project / "ids_agent.skye")]) == 0
    assert ": ok" in capsys.readouterr().out


def test_check_names_a_bad_override_with_its_fix(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text = WHOLE.replace("override show_ids", "override missing")
    (project / "ids_agent.skye").write_text(text, encoding="utf-8")
    assert main(["check", str(project / "ids_agent.skye")]) == 1
    out = capsys.readouterr().out
    assert (
        'cannot override "missing"' in out
        and "brought: show_ids" in out
        and "Write the use before the override." in out
    )


def test_check_json_gives_the_use_site_of_a_mistake_left_in_the_partial(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (project / "lib" / "memories.skye").write_text(
        MEMORIES.replace("when persona_memory {", "when nothing_here {"), encoding="utf-8"
    )
    assert main(["check", "--format", "json", str(project / "ids_agent.skye")]) == 1
    found = json.loads(capsys.readouterr().out)["diagnostics"]
    assert found[0]["file"].endswith("memories.skye") and found[0]["via"][0]["file"].endswith(
        "ids_agent.skye"
    )


def test_check_json_of_a_file_without_override_keeps_its_six_keys(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "bad.skye").write_text(
        'prompt "p" {\n  message "user" { text = "{{ nothing }}" }\n}\n', encoding="utf-8"
    )
    assert main(["check", "--format", "json", str(tmp_path / "bad.skye")]) == 1
    found = json.loads(capsys.readouterr().out)["diagnostics"][0]
    assert "via" not in found and len(found) == 6


def test_fmt_keeps_the_override_lines(project: Path) -> None:
    messy = project / "ids_agent.skye"
    messy.write_text(WHOLE.replace("\n  ", "\n      "), encoding="utf-8")
    assert main(["fmt", "--check", str(messy)]) == 1
    assert main(["fmt", str(messy)]) == 0
    assert messy.read_text(encoding="utf-8") == WHOLE
    assert main(["fmt", str(project)]) == 0  # the folder, the partial included
    assert main(["fmt", "--check", str(project)]) == 0
    assert "override show_ids" in messy.read_text(encoding="utf-8")


def test_prompt_list_skips_a_partial_that_holds_the_overridden_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = tmp_path / "templates"
    folder.mkdir()
    (folder / "chat.skye").write_text(
        '---\ntitle = "Chat"\nversion = "1.0"\n---\n'
        'prompt "chat" {\n  message "system" { text = "hi" }\n}\n',
        encoding="utf-8",
    )
    (folder / "memories.skye").write_text(MEMORIES, encoding="utf-8")
    monkeypatch.setattr(loaders, "TEMPLATES_DIR", folder)
    monkeypatch.setattr(loaders, "_archive_index", None)
    assert main(["prompt", "list"]) == 0
    out = capsys.readouterr().out
    assert "chat" in out and "memories" not in out
