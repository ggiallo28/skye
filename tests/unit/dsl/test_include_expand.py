"""The expansion of include, from-import and use gives the file written without them."""

from __future__ import annotations

from skye.base.dsl import build, parse
from tests.unit.dsl.include_files import (
    CHAT_AGENT,
    CHAT_AGENT_EXPANDED,
    TOOL_AGENT,
    TOOL_AGENT_EXPANDED,
    built,
    plain,
    resolver,
)


def test_names_taken_one_by_one_from_two_files_equal_the_expanded_prompt():
    document = built(TOOL_AGENT)
    assert document.ok, document.diagnostics
    expected = build(TOOL_AGENT_EXPANDED)
    assert expected.ok, expected.diagnostics
    assert plain(document.prompt()) == plain(expected.prompt())


def test_the_variables_are_in_the_order_of_the_use_lines():
    names = [v.name for v in built(TOOL_AGENT).prompt().variables]
    assert names == [
        "system_prompt",
        "tools",
        "examples",
        "input",
        "persona_memory",
        "episodic_memory",
    ]


def test_a_whole_file_brings_its_variables_and_the_body_of_its_message():
    document = built(CHAT_AGENT)
    assert document.ok, document.diagnostics
    expected = build(CHAT_AGENT_EXPANDED)
    assert plain(document.prompt()) == plain(expected.prompt())


def test_two_prompts_take_different_names_from_the_same_files():
    text = (
        'from "lib/agent.skye"  import system_prompt\n'
        'from "lib/memory.skye" import persona_memory\n\n'
        'prompt "chat_agent" {\n  variables = {\n    use system_prompt\n    use persona_memory\n'
        '    input = string("")  "The user\'s message"\n  }\n  message "system" {\n'
        "    use system_prompt\n    when persona_memory { use persona_memory }\n  }\n}\n"
    )
    document = built(text)
    assert document.ok, document.diagnostics
    prompt = document.prompt()
    assert [v.name for v in prompt.variables] == ["system_prompt", "persona_memory", "input"]
    message = prompt.parts[0]
    assert [c.kind for c in message.children] == ["when", "when", "when"]
    # `when persona_memory { use persona_memory }` holds the text of the memory, wrapped once more
    assert message.children[2].children[0].kind == "when"


def test_a_whole_file_in_the_prompt_body_brings_its_messages():
    text = (
        'include "lib/agent.skye" as agent\n\nprompt "p" {\n  variables = {\n    use agent\n  }\n'
        "  use agent\n}\n"
    )
    document = built(text)
    assert document.ok, document.diagnostics
    (message,) = document.prompt().parts
    assert message.kind == "message" and message.role == "system"


def test_a_wider_condition_is_never_brought_by_a_name():
    files = {
        "lib/x.skye": (
            '---\npartial = true\n---\nprompt "x" {\n'
            "  variables = { a = string, b = string }\n"
            '  message "system" {\n    when a or b { text = "either" }\n'
            '    when a { text = "{{ a }}" }\n  }\n}\n'
        )
    }
    text = (
        'from "lib/x.skye" import a\nprompt "p" {\n  variables = {\n    use a\n  }\n'
        '  message "system" {\n    use a\n  }\n}\n'
    )
    document = built(text, files)
    assert document.ok, document.diagnostics
    (message,) = document.prompt().parts
    assert len(message.children) == 1 and message.children[0].condition.text == "a"


def test_an_imported_name_can_be_renamed():
    text = (
        'from "lib/agent.skye" import tools as skills\nprompt "p" {\n  variables = {\n'
        '    use skills\n  }\n  message "system" {\n    use skills\n  }\n}\n'
    )
    document = built(text)
    assert document.ok, document.diagnostics
    assert [v.name for v in document.prompt().variables] == ["tools"]


def test_the_tree_is_not_changed_and_can_be_built_again():
    tree = parse(TOOL_AGENT, "app.skye")
    first = build(tree, resolver=resolver())
    second = build(tree, resolver=resolver())
    assert first.ok and plain(first.prompt()) == plain(second.prompt())
    assert tree.blocks[0].kind == "from"  # the include lines are still in the caller's tree


def test_the_resolver_gets_the_target_and_the_key_of_the_including_file():
    calls: list[tuple[str, str | None]] = []
    build(CHAT_AGENT, filename="app.skye", key="/abs/app.skye", resolver=resolver(calls=calls))
    assert calls == [("lib/memory.skye", "/abs/app.skye")]
    calls.clear()
    build(CHAT_AGENT, filename="app.skye", resolver=resolver(calls=calls))
    assert calls == [("lib/memory.skye", "app.skye")]


def test_nodes_from_a_partial_know_where_they_come_from():
    from skye.base.dsl.include import expand

    tree, errors = expand(parse(CHAT_AGENT, "app.skye"), resolver())
    assert not errors
    entry = tree.blocks[0].body[0].value.entries[0]
    assert entry.key == "persona_memory"
    assert entry.source == "lib/memory.skye"
    assert entry.via == (("app.skye", 5, 5),)
    assert entry.value.source == "lib/memory.skye"


def test_a_file_without_include_is_not_expanded():
    calls: list[tuple[str, str | None]] = []
    build(TOOL_AGENT_EXPANDED, resolver=resolver(calls=calls))
    assert calls == []
