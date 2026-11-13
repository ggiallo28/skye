"""The diagnostics of include: ``via``, a partial checked alone, and ``use`` outside prompts."""

from __future__ import annotations

import json

import pytest

from skye.base.dsl import Diagnostic, Resolved, build, check_text
from skye.utils import cli

PARTIAL = (
    '---\npartial = true\n---\nprompt "m" {\n  variables = { a = string "A" }\n'
    '  message "system" {\n    when a { text = "{{ a }}" }\n  }\n}\n'
)
USER = (
    'include "lib/m.skye" as m\nprompt "x" {\n  variables = {\n    use m\n  }\n'
    '  message "system" {\n    use m\n  }\n}\n'
)


def resolver_of(files):
    def resolve(target, from_key):
        return Resolved(text=files[target], name=target, key=target)

    return resolve


def test_a_mistake_in_a_partial_names_the_partial_and_the_use_site():
    bad = PARTIAL.replace("{{ a }}", "{{ b }}")
    (problem,) = check_text(USER, "app.skye", resolver=resolver_of({"lib/m.skye": bad}))
    assert (problem.file, problem.line, problem.column) == ("lib/m.skye", 7, 21)
    assert problem.via == (("app.skye", 7, 5),)
    assert problem.format().endswith(" (used from app.skye:7:5)")
    assert problem.format().startswith('lib/m.skye:7:21 variable "b" is not declared')


def test_a_diagnostic_without_include_has_no_via_and_the_same_text():
    problem = Diagnostic(file="a.skye", line=1, column=2, reason="bad.", fix="Fix it.")
    assert problem.via == ()
    assert problem.format() == "a.skye:1:2 bad. Fix it."


def test_one_segment_for_each_use_site():
    problem = Diagnostic(
        file="l.skye", line=3, column=4, reason="bad.", via=(("a", 1, 2), ("b", 5, 6))
    )
    assert problem.format() == "l.skye:3:4 bad. (used from a:1:2) (used from b:5:6)"


def _json(capsys, tmp_path, text):
    path = tmp_path / "app.skye"
    path.write_text(text)
    status = cli.main(["check", str(path), "--format", "json"])
    return status, json.loads(capsys.readouterr().out), str(path)


def test_the_json_of_a_diagnostic_without_include_keeps_its_keys(capsys, tmp_path):
    status, out, path = _json(capsys, tmp_path, 'prompt "p" {\n  nope = 1\n}\n')
    assert status == 1
    (item,) = out["diagnostics"]
    assert list(item) == ["file", "line", "column", "reason", "fix", "message"]


def test_the_json_adds_via_only_for_a_brought_node(capsys, tmp_path, monkeypatch):
    shown = Diagnostic(
        file="lib/m.skye", line=7, column=21, reason="bad.", via=(("app.skye", 7, 5),)
    )
    plain = Diagnostic(file="app.skye", line=1, column=1, reason="bad.")
    monkeypatch.setattr(cli, "check_text", lambda *a, **k: [shown, plain])
    _status, out, _path = _json(capsys, tmp_path, "")
    first, second = out["diagnostics"]
    assert first["via"] == [{"file": "app.skye", "line": 7, "column": 5}]
    assert list(first)[:6] == ["file", "line", "column", "reason", "fix", "message"]
    assert "via" not in second


def test_a_partial_checked_alone_has_no_error_and_says_where_the_rest_is_checked(capsys, tmp_path):
    path = tmp_path / "m.skye"
    path.write_text(PARTIAL)
    assert check_text(PARTIAL, "lib/m.skye") == []
    assert cli.main(["check", str(path)]) == 0
    assert "(a partial: the rest is checked where it is used)" in capsys.readouterr().out


def test_a_partial_with_a_syntax_error_is_still_reported():
    broken = PARTIAL.replace('string "A" }', 'string "A"')  # the map is never closed
    problems = check_text(broken, "lib/m.skye")
    assert problems and all(p.file == "lib/m.skye" for p in problems)


def test_building_a_partial_alone_is_still_an_error():
    (problem,) = build(PARTIAL, filename="lib/m.skye").diagnostics
    assert "cannot be built alone" in problem.reason


@pytest.mark.parametrize(
    "text",
    [
        'router "r" {\n  use m\n}\n',
        'flow "f" {\n  use m\n}\n',
        "use m\n",
    ],
)
def test_a_use_outside_a_prompt_says_it_is_for_prompts_only(text):
    reasons = [d.reason for d in check_text(text, "app.skye")]
    assert "use is available in prompts only." in reasons
    assert not any("unknown" in r and '"use"' in r for r in reasons)


@pytest.mark.parametrize("line", ['include "lib/m.skye" as m', 'from "lib/m.skye" import a'])
def test_include_and_from_in_a_file_of_routers_and_flows_say_prompts_only(line):
    text = line + '\nrouter "r" {\n  strategy = "round_robin"\n}\n'
    (problem,) = check_text(text, "app.skye")
    assert problem.reason.endswith("is available in prompts only.")
    assert (problem.line, problem.column) == (1, 1)
    assert problem.fix == "Write it in a file that has a prompt."


def test_a_file_with_a_prompt_and_a_router_may_include():
    files = {"lib/m.skye": PARTIAL}
    text = USER + 'router "r" {\n  strategy = "round_robin"\n}\n'
    assert check_text(text, "app.skye", resolver=resolver_of(files)) == []


def test_the_messages_of_the_table_read_as_one_sentence():
    files = {"lib/m.skye": PARTIAL}
    bad_import = 'from "lib/m.skye" import zz\nprompt "p" {\n}\n'
    (problem,) = check_text(bad_import, "app.skye", resolver=resolver_of(files))
    assert problem.message == '"lib/m.skye" has no variable "zz"; it has: a'
    no_alias = 'include "lib/m.skye"\nprompt "p" {\n}\n'
    (problem,) = check_text(no_alias, "app.skye", resolver=resolver_of(files))
    assert problem.message == 'an include needs a name Write: include "lib/m.skye" as <name>'
