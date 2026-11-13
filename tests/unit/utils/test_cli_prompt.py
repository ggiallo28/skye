"""``skye prompt list`` and ``skye prompt info``."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from skye.utils.cli import main

PROMPT = """\
prompt "ask" {
  variables = { question = string "What the user asks", tone = string("brief") }
  message "user" { text = "{{ question }} ({{ tone }})" }
  output { answer = string "The answer" }
}

prompt "other" {
  message "user" { text = "hi" }
}
"""


def test_list(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["prompt", "list"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("agent_react")  # the names are listed in order, the first is agent_react
    assert "agent_react" in out and "ReAct agent (1.0)" in out


def test_list_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["prompt", "list", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    planner = next(r for r in rows if r["name"] == "agent_react")
    assert set(planner) == {"name", "title", "version", "description"}
    assert planner["version"] == "1.0"


def test_info_of_a_bundled_prompt(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["prompt", "info", "agent_react"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("agent_react — ReAct agent (1.0)\n")
    for section in ("\nInputs\n", "\nHistory\n", "\nMessages\n", "\nOutput\n"):
        assert section in out


def test_info_of_a_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "ask.skye"
    path.write_text(PROMPT, encoding="utf-8")
    assert main(["prompt", "info", str(path), "--name", "ask"]) == 0
    assert capsys.readouterr().out == (
        "ask\n\nInputs\n"
        "  question  string  required   What the user asks\n"
        '  tone      string  = "brief"\n'
        "\nHistory\n  (none)\n\nMessages\n  user\n\n"
        "Output (json)\n  answer  string  required  The answer\n"
    )


def test_info_needs_name_when_the_file_has_several(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "ask.skye"
    path.write_text(PROMPT, encoding="utf-8")
    assert main(["prompt", "info", str(path)]) == 2
    assert "2 prompt blocks" in capsys.readouterr().err
    assert main(["prompt", "info", str(path), "--name", "nope"]) == 2
    assert 'no prompt "nope"' in capsys.readouterr().err


def test_info_from_stdin_as_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(PROMPT))
    assert main(["prompt", "info", "-", "--name", "ask", "--json"]) == 0
    info = json.loads(capsys.readouterr().out)
    assert info["name"] == "ask"
    assert info["inputs"][0]["description"] == "What the user asks"
    assert info["output"]["fields"][0]["name"] == "answer"


def test_info_of_a_file_with_mistakes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO('prompt "a" {\n  variables = { q = strin }\n}\n'))
    assert main(["prompt", "info", "-"]) == 1
    assert "<stdin>:2:" in capsys.readouterr().out


def test_info_of_an_unknown_name(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["prompt", "info", "no_such_prompt"]) == 2
    err = capsys.readouterr().err
    assert "neither a bundled prompt nor a file" in err
    assert "agent_react" in err
