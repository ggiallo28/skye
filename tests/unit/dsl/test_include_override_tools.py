"""The tools of the ``override`` of the include (D117, Requirement 63.21): fmt, diagnostics, via, to_text."""

from __future__ import annotations

import pytest

from skye.base.dsl import fmt as fmt_module
from skye.base.dsl.emit import to_text
from skye.base.dsl.fmt import FormatError, _shape, format_text
from skye.base.dsl.parser import parse_collect
from tests.unit.dsl.include_files import built, reasons
from tests.unit.dsl.test_include_override import FILES, MEMORIES, WHOLE


def test_fmt_keeps_the_override_lines_where_they_are_and_is_idempotent():
    messy = WHOLE.replace("\n  ", "\n      ")
    once = format_text(messy, "app.skye")
    assert once == WHOLE
    assert format_text(once, "app.skye") == once
    assert "    override show_ids = bool(true)" in once
    assert "    override when not show_ids {" in once


def test_fmt_formats_what_is_inside_an_override():
    squeezed = WHOLE.replace(
        'override when not show_ids { text = "Ids are hidden." }',
        'override when not show_ids {\ntext = "Ids are hidden."\n}',
    )
    assert 'override when not show_ids {\n      text = "Ids are hidden."\n    }' in format_text(
        squeezed, "app.skye"
    )


def test_the_tree_comparison_of_fmt_sees_the_override_flags():
    kept, _ = parse_collect(WHOLE, "app.skye")
    lost, _ = parse_collect(WHOLE.replace("override show_ids", "show_ids"), "app.skye")
    assert _shape(kept) != _shape(lost)


def test_fmt_refuses_a_result_that_lost_an_override(monkeypatch: pytest.MonkeyPatch):
    real = fmt_module._layout
    monkeypatch.setattr(
        fmt_module, "_layout", lambda body: [line.replace("override ", "") for line in real(body)]
    )
    with pytest.raises(FormatError, match="would change what the file means"):
        format_text(WHOLE, "app.skye")


def test_an_invalid_override_is_reported_at_the_override_line_of_the_file():
    bad = WHOLE.replace(
        'override show_ids = bool(true)  "Ids are shown"',
        'override show_ids = nonsense(1)  "Ids are shown"',
    )
    problem = built(bad, FILES).diagnostics[0]
    assert (problem.file, problem.line) == ("app.skye", 6)
    assert not problem.via


def test_a_mistake_left_in_the_part_a_partial_still_brings_points_at_the_partial_with_the_use_site():
    broken = {"lib/memories.skye": MEMORIES.replace("when persona_memory {", "when nothing_here {")}
    problem = built(WHOLE, broken).diagnostics[0]
    assert problem.file == "lib/memories.skye"
    assert [(v[0], v[1]) for v in problem.via] == [
        ("app.skye", 10)
    ]  # the ``use memories`` of the message


def test_an_override_of_a_name_whose_use_comes_later_says_where_the_use_is():
    early = (
        'from "lib/memories.skye" import show_ids\n'
        'prompt "p" {\n  variables = {\n    override show_ids = bool(true)  "Shown"\n    use show_ids\n  }\n}\n'
    )
    problems = reasons(built(early, FILES))
    assert any('cannot override "show_ids"' in p for p in problems)
    fixes = [d.fix for d in built(early, FILES).diagnostics]
    assert any(
        'The use of "show_ids" is at line 5; write the override after it.' in f for f in fixes
    )


def test_a_second_override_of_a_name_says_where_the_first_one_is():
    twice = WHOLE.replace(
        '    override show_ids = bool(true)  "Ids are shown"',
        '    override show_ids = bool(true)  "Ids are shown"\n    override show_ids = bool(false)  "Again"',
    )
    assert any("already overridden at line 6" in r for r in reasons(built(twice, FILES)))


def test_an_override_when_in_a_router_is_reported_as_prompts_only():
    text = 'router "r" {\n  override when x { next = "a" }\n}\n'
    document = built(text, FILES)
    assert "override is available in prompts only." in reasons(document)


def test_to_text_of_a_prompt_with_an_override_writes_the_expanded_text():
    document = built(WHOLE, FILES)
    assert document.ok
    text = to_text(document.prompts[0])
    assert "override" not in text and "use " not in text and "include" not in text
    assert "show_ids = bool(true)" in text
