"""The include forms parse (Requirement 63, D116); the new words are words only in their places."""

from __future__ import annotations

from skye.base.dsl import build, parse
from skye.base.dsl.tree import Block, MapNode


def test_include_takes_a_path_and_a_name():
    tree = parse('include "lib/memory.skye" as memory\n')
    (block,) = tree.blocks
    assert (block.kind, block.label_text, block.var) == ("include", "lib/memory.skye", "memory")
    assert tree.has_include


def test_an_include_without_as_parses_and_is_reported_when_expanded():
    (block,) = parse('include "lib/memory.skye"\n').blocks
    assert block.var == ""


def test_from_import_lists_names_and_renames():
    (block,) = parse('from "lib/agent.skye" import system_prompt, tools as t\n').blocks
    assert block.kind == "from" and block.label_text == "lib/agent.skye"
    assert [(i.label_text, i.var) for i in block.body] == [("system_prompt", ""), ("tools", "t")]


def test_use_is_an_entry_of_variables_and_a_block_in_a_body():
    tree = parse(
        'prompt "p" {\n  variables = {\n    use common\n    a = string\n  }\n'
        '  message "system" {\n    use common\n    when a { use other }\n  }\n}\n'
    )
    prompt = tree.blocks[0]
    variables = prompt.body[0].value
    assert isinstance(variables, MapNode)
    assert [(e.key, e.use) for e in variables.entries] == [("common", True), ("a", False)]
    message = prompt.body[1]
    assert isinstance(message, Block) and message.body[0].kind == "use"
    assert message.body[1].body[0].kind == "use"
    assert tree.has_include


def test_a_file_without_include_does_not_set_the_flag():
    assert not parse('prompt "p" {\n  variables = { a = string }\n}\n').has_include


def test_the_new_words_are_free_elsewhere():
    text = (
        'prompt "p" {\n  variables = {\n    from = string\n    use = string\n'
        "    as = string\n    import = string\n    include = string\n    partial = string\n  }\n"
        '  message "system" {\n    text = "{{ from }} {{ use }} {{ as }}"\n  }\n}\n'
    )
    document = build(text)
    assert document.ok, document.diagnostics
    assert [v.name for v in document.prompt().variables] == [
        "from",
        "use",
        "as",
        "import",
        "include",
        "partial",
    ]


def test_use_inside_a_nested_map_of_variables_is_not_an_entry():
    document = build('prompt "p" {\n  variables = {\n    x = list({ use = string }, [])\n  }\n}\n')
    assert document.ok, document.diagnostics


def test_include_is_no_longer_a_reserved_version_2_word():
    document = build('include "x.skye" as x\n')
    assert "is not available in this version" not in " ".join(
        d.message for d in document.diagnostics
    )
