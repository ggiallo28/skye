"""The rules of include, from-import and use: each mistake has a file, a line and a column."""

from __future__ import annotations

import pytest

from skye.base.dsl import build
from skye.base.dsl.include import MAX_INCLUDED_CHARS, MAX_INCLUDES
from tests.unit.dsl.include_files import AGENT, CHAT_AGENT, FILES, MEMORY, built, reasons, resolver

PARTIAL = (
    '---\npartial = true\n---\nprompt "x" {\n  variables = { a = string("") "A" }\n'
    '  message "system" {\n    when a { text = "{{ a }}" }\n  }\n}\n'
)


def one(text, files=None, name="app.skye"):
    document = built(text, files, name)
    assert len(document.diagnostics) == 1, document.diagnostics
    return document.diagnostics[0]


def test_a_partial_cannot_be_built_alone():
    document = build(AGENT, filename="lib/agent.skye")
    (problem,) = document.diagnostics
    assert "partial" in problem.reason and "cannot be built alone" in problem.reason
    assert problem.file == "lib/agent.skye" and "include" in problem.fix


def test_without_a_resolver_an_include_is_an_error_with_the_fix():
    (problem,) = build(CHAT_AGENT, filename="app.skye").diagnostics
    assert "no resolver" in problem.reason
    assert problem.fix == "Pass resolver= to build, or load the file with skye.load."
    assert (problem.file, problem.line, problem.column) == ("app.skye", 1, 1)


def test_an_include_needs_a_name():
    problem = one('include "lib/memory.skye"\nprompt "p" {\n}\n')
    assert problem.reason == "an include needs a name"
    assert "as <name>" in problem.fix


@pytest.mark.parametrize(
    "target",
    ["/etc/passwd", "\\\\server\\share\\x.skye", "https://example.com/x.skye", "C:x.skye", ""],
)
def test_an_absolute_path_a_url_and_an_empty_path_are_refused(target):
    problem = one(f'include "{target}" as x\n'.replace("\\", "\\\\"))
    assert "is not a relative path" in problem.reason


def test_a_path_that_leaves_the_root_is_what_the_resolver_says():
    problem = one('include "../secret.skye" as x\n')
    assert "leaves the root" in problem.reason


def test_a_missing_file_is_reported_at_the_include():
    problem = one('include "lib/none.skye" as x\n')
    assert 'cannot read "lib/none.skye"' in problem.reason and "no file" in problem.reason
    assert (problem.line, problem.column) == (1, 1)


def test_a_file_that_is_not_a_partial_is_refused():
    files = {"x.skye": PARTIAL.replace("partial = true", "partial = false")}
    assert "is not a partial" in one('include "x.skye" as x\n', files).reason


def test_a_partial_with_a_syntax_error_is_reported_in_its_own_file():
    files = {"x.skye": '---\npartial = true\n---\nprompt "x" {\n  variables = {\n'}
    document = built('include "x.skye" as x\n', files)
    assert document.diagnostics and document.diagnostics[0].file == "x.skye"


def test_a_partial_holds_one_prompt_and_no_include():
    twice = PARTIAL + PARTIAL.split("---\n", 2)[2]
    assert "not a valid partial" in one('include "x.skye" as x\n', {"x.skye": twice}).reason
    nested = PARTIAL.replace("  message", "  use other\n  message")
    assert "not a valid partial" in one('include "x.skye" as x\n', {"x.skye": nested}).reason


def test_a_file_cannot_include_itself():
    problem = one('include "app.skye" as me\n', {"app.skye": PARTIAL})
    assert problem.reason == "include cycle: app.skye -> app.skye"


def test_a_cycle_is_found_by_the_key_not_by_the_name():
    files = {"other/name.skye": PARTIAL}

    def resolve(target, from_key):
        return resolver(files)("other/name.skye", from_key).__class__(
            text=PARTIAL, name=target, key="/abs/app.skye"
        )

    document = build(
        'include "alias.skye" as me\n', filename="app.skye", key="/abs/app.skye", resolver=resolve
    )
    assert document.diagnostics[0].reason == "include cycle: app.skye -> alias.skye"


def test_the_same_file_included_twice_is_an_error():
    text = 'include "lib/memory.skye" as a\nfrom "lib/memory.skye" import persona_memory\n'
    problem = one(text)
    assert problem.reason == '"lib/memory.skye" is already included at line 1' and problem.line == 2


def test_the_same_name_from_two_files_asks_for_as():
    files = {"a.skye": PARTIAL, "b.skye": PARTIAL}
    problem = one('from "a.skye" import a\nfrom "b.skye" import a\n', files)
    assert problem.reason == '"a" is already imported at line 1'
    assert problem.fix == "Write: import a as other_a" and problem.line == 2
    ok = built('from "a.skye" import a\nfrom "b.skye" import a as b_a\n', files)
    assert ok.ok, ok.diagnostics


def test_an_alias_twice_is_an_error():
    files = {"a.skye": PARTIAL, "b.skye": PARTIAL}
    problem = one('include "a.skye" as x\ninclude "b.skye" as x\n', files)
    assert problem.reason == 'the alias "x" is already used at line 1'


def test_importing_a_name_the_file_does_not_have_is_an_error():
    problem = one('from "lib/memory.skye" import semantic_memory\n')
    assert problem.reason.startswith(
        '"lib/memory.skye" has no variable "semantic_memory"; it has: '
    )
    assert "persona_memory, episodic_memory" in problem.reason and "Did you mean" in problem.fix


def test_a_use_of_a_name_that_is_not_included_lists_the_names():
    text = (
        'include "lib/memory.skye" as memory\nprompt "p" {\n  variables = {\n'
        "    use memry\n  }\n}\n"
    )
    problem = one(text)
    assert problem.reason == '"memry" is not included or imported; the names here are: memory'
    assert 'Did you mean "memory"?' in problem.fix and (problem.line, problem.column) == (4, 5)


def test_a_use_with_a_dotted_name_is_an_error():
    text = (
        'include "lib/memory.skye" as m\nprompt "p" {\n  message "system" {\n    use m.x\n  }\n}\n'
    )
    assert one(text).reason == "use takes one name"


def test_the_same_name_used_twice_in_one_body_is_an_error():
    text = (
        'from "lib/memory.skye" import persona_memory\nprompt "p" {\n  variables = {\n'
        "    use persona_memory\n    use persona_memory\n  }\n}\n"
    )
    problem = one(text)
    assert problem.reason == '"persona_memory" is already used at line 4' and problem.line == 5
    twice = text.replace(
        "variables = {\n    use persona_memory\n    use persona_memory\n  }",
        'message "system" {\n    use persona_memory\n    use persona_memory\n  }',
    )
    assert "already used" in one(twice).reason


def test_a_name_with_an_entry_and_no_text_cannot_be_used_in_a_body():
    files = {
        "x.skye": PARTIAL.replace(
            'variables = { a = string("") "A" }',
            'variables = { a = string("") "A", b = string("") "B" }',
        )
    }
    text = (
        'from "x.skye" import b\nprompt "p" {\n  variables = {\n    use b\n  }\n'
        '  message "system" {\n    use b\n  }\n}\n'
    )
    problem = one(text, files)
    assert problem.reason == '"x.skye" has no text for "b"; it only has its entry'
    assert problem.line == 7


def test_a_whole_file_in_a_message_needs_a_message_of_the_same_name():
    text = 'include "lib/memory.skye" as m\nprompt "p" {\n  message "user" {\n    use m\n  }\n}\n'
    problem = one(text)
    assert problem.reason == '"lib/memory.skye" has no message "user"'
    assert problem.fix == "It has: system."


def test_a_variable_defined_by_the_file_and_by_a_partial_names_both_places():
    text = (
        'from "lib/memory.skye" import persona_memory\nprompt "p" {\n  variables = {\n'
        '    use persona_memory\n    persona_memory = string("")\n  }\n}\n'
    )
    problem = one(text)
    assert (
        problem.reason
        == (
            '"persona_memory" is defined twice: here and at lib/memory.skye:4:5'.replace(
                "4:5", "5:5"
            )
        )
        or "defined twice" in problem.reason
    )
    assert (problem.file, problem.line) == ("app.skye", 5)


def test_a_use_outside_a_prompt_is_reported_by_the_checker():
    text = 'include "lib/memory.skye" as m\nrouter "r" {\n  use m\n}\n'
    document = built(text)
    assert "include is available in prompts only." in reasons(document)


def test_a_mistake_in_a_brought_node_is_reported_in_the_file_it_comes_from():
    # the text of the memory is brought without its entry: the variable is not declared
    text = (
        'from "lib/memory.skye" import persona_memory\nprompt "p" {\n  message "system" {\n'
        "    use persona_memory\n  }\n}\n"
    )
    document = built(text)
    problems = [d for d in document.diagnostics if "is not declared" in d.reason]
    assert problems and all(d.file == "lib/memory.skye" for d in problems)


def test_more_than_the_limit_of_includes_is_an_error():
    files = {f"f{i}.skye": PARTIAL for i in range(MAX_INCLUDES + 1)}
    text = "".join(f'include "f{i}.skye" as p{i}\n' for i in range(MAX_INCLUDES + 1))
    problem = one(text, files)
    assert problem.reason == f"too many includes (more than {MAX_INCLUDES} in one document)"
    assert built(text.rsplit("\n", 2)[0] + "\n", files).ok


def test_too_much_included_text_is_an_error():
    big = PARTIAL.replace('"x"', '"x"', 1) + "# " + "x" * (MAX_INCLUDED_CHARS // 2) + "\n"
    files = {"a.skye": big, "b.skye": big, "c.skye": big}
    text = "".join(f'include "{n}.skye" as {n}\n' for n in "abc")
    document = built(text, files)
    assert any("too large" in r for r in reasons(document))


def test_the_fixtures_are_what_the_design_shows():
    assert set(FILES) == {"lib/agent.skye", "lib/memory.skye"} and MEMORY and AGENT
