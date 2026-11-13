"""The bundled templates after the move to partials (task 24.6, Requirement 63.16).

The templates repeated the same declarations and text (``system_prompt``, ``tools``, the five memories),
so they take them from partials in ``templates/common/`` with ``include``. What a template builds and
renders must not change, except for the changes listed in ``CHANGES``, which the move made on purpose.

``fixtures/templates_before.json`` was made from the 40 templates as they were before the move:

* ``before``: for each template and each way of rendering it (see ``_variable_sets``), a digest of the
  messages. Rendering is compared exactly; the built prompt is compared by its declarations (name, output,
  variables taken by name, without the optional ``id`` that the memory items now declare).
* ``after``: for each (template, rendering) of ``CHANGES``, the digest of the intended new text, and
  ``after_text`` the new text itself for the renderings of one variable, so a change can be read.

``write_fixture(folder)`` makes the file again: it takes the ``before`` side from a folder of templates
and the ``after`` side from the templates as they are now.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

import pytest

from skye.prompts import BasePromptBuilder, loaders, messages
from tests.unit.prompts.bundled import GALLERY_DIR, gallery_builder, template_path

FIXTURE = Path(__file__).parent / "fixtures" / "templates_before.json"
POSITIONS = {"line", "column", "source", "via", "style", "style_from"}  # style: the text output, unset here
MEMORIES = (
    "persona_memory",
    "episodic_memory",
    "semantic_memory",
    "procedural_memory",
    "working_memory",
)
SHARED = {"system_prompt", "tools", *MEMORIES}

#: The catalogue of task 24.10: the name each template of the fixture has now (the fixture keeps the names
#: it was made with). The renders of a renamed template are compared with those it had before.
NEW_NAME = {
    "chain_of_thought_agent": "agent_reasoning_chain_of_thought",
    "chat": "chat_assistant",
    "classification": "text_classification",
    "code_agent": "agent_code",
    "code_generation": "generation_code",
    "explanation": "text_explanation",
    "form_agent": "agent_form",
    "group_chat_manager": "agent_groupchat_manager",
    "group_chat_participant": "agent_groupchat_participant",
    "group_chat_summarizer": "agent_groupchat_summarizer",
    "main_agent": "agent_memory_assistant",
    "memory_agent": "agent_memory_recall",
    "memory_consolidation_agent": "agent_memory_consolidation",
    "memory_update_agent": "agent_memory_update",
    "multimodal_agent": "agent_multimodal",
    "ner": "extraction_entities",
    "planner_agent": "agent_planner",
    "procedure_agent": "agent_procedure",
    "question_answering": "text_question_answering",
    "reasoning_agent": "agent_reasoning",
    "relation_extraction": "extraction_relations",
    "self_reflection_agent": "agent_reasoning_self_reflection",
    "smol_code_agent": "agent_smol_code",
    "smol_managed_agent": "agent_smol_managed",
    "smol_planning": "agent_smol_planning",
    "smol_tool_calling_agent": "agent_react",
    "sql_generation": "generation_sql",
    "structured_output": "extraction_structured",
    "summarization": "text_summarization",
    "supervisor_hierarchical": "agent_supervisor_hierarchical",
    "supervisor_planner": "agent_supervisor_planner",
    "supervisor_reviewer": "agent_supervisor_reviewer",
    "supervisor_router": "agent_supervisor_router",
    "tabular_extraction": "extraction_table",
    "tool_agent": "agent_tool",
    "tree_of_thoughts_agent": "agent_reasoning_tree_of_thoughts",
    "working_memory_agent": "agent_memory_working",
}
#: Removed from the catalogue (task 24.10): ``structured_output`` takes the format in its ``format`` variable.
REMOVED = ("structured_output_json", "structured_output_table", "structured_output_xml")

#: The renderings that change on purpose: template -> (the renderings, what changed). Every other
#: (template, rendering) is byte for byte what it was.
_TOOLS = "The introduction of the tools says 'You may call these tools when they help; when a tool would not help, answer without it.'"
_IDS_SENTENCE = (
    "The sentence 'An item that has an id shows it first, in square brackets; refer to the item by that id.' is written "
    "in the template, after the memory section, and no longer under the '## Memory' heading; the episodic items "
    "without an id are '[ts] content' as in every other template (they were 'content (at ts)')."
)
CHANGES: dict[str, tuple[tuple[str, ...], str]] = {
    "structured_output": (
        ("full", "ids"),
        "The error for an unknown value of the `format` variable lists the four formats (json, table, xml or text).",
    ),
    "code_agent": (("full", "only_tools"), _TOOLS + " (it said 'You can call these tools:')."),
    "reasoning_agent": (("full", "only_tools"), _TOOLS + " (it said 'You can call these tools:')."),
    "procedure_agent": (("full", "only_tools"), _TOOLS + " (it said 'You can call these tools:')."),
    "form_agent": (
        ("full", "only_tools"),
        _TOOLS + " (it said 'These tools are available to you; use them when they help.').",
    ),
    "multimodal_agent": (
        ("full", "only_tools"),
        _TOOLS + " (it said 'These tools are available to you; use them when they help.').",
    ),
    "main_agent": (
        (
            "full",
            "only_tools",
            "only_episodic_memory",
            "only_semantic_memory",
            "only_procedural_memory",
        ),
        "The memories are the standard section '## Memory' with '### Past events', '### Known facts' and "
        "'### Procedures' (they were three sections of their own, '## Context of things the Human said in the past:', "
        "'## Context of documents containing relevant information:' and a list of procedures); "
        + _TOOLS,
    ),
    "memory_agent": (
        ("full", "only_tools", "only_episodic_memory", "only_semantic_memory"),
        "The memories are the standard section '## Memory' with '### Past events' and '### Known facts' (they were two "
        "sections of their own, '## Context of things the Human said in the past:' and "
        "'## Context of documents containing relevant information:'); " + _TOOLS,
    ),
    **{
        name: (
            (
                "full",
                "only_persona_memory",
                "only_episodic_memory",
                "only_semantic_memory",
                "only_procedural_memory",
                "only_working_memory",
            ),
            _IDS_SENTENCE,
        )
        for name in ("memory_consolidation_agent", "memory_update_agent")
    },
    "working_memory_agent": (("full",), _IDS_SENTENCE),
    **{
        name: (
            ("full",),
            "The memory headings are the standard ones ('### Persona', '### Past events', '### Known facts', "
            "'### Procedures', '### Current notes'), the sections come in the standard order and the lines of "
            "episodic and semantic items and of procedures are the standard ones.",
        )
        for name in (
            "smol_code_agent",
            "smol_managed_agent",
            "smol_planning",
            "smol_tool_calling_agent",
        )
    },
}

#: The memory-upkeep templates: they take the standard section and add, right after it, the sentence that
#: tells the agent that an item shows its id, so that it can change the item by that id.
KEEP_THE_SECTION = ("memory_consolidation_agent", "memory_update_agent", "working_memory_agent")


def _plain(value, memory: bool = False):
    """The value with its fields in order and without the positions of the source.

    The items of a memory declare an optional ``id`` now; it is left out, so that the declarations of
    a template are compared as they were before.
    """
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        memory = memory or getattr(value, "name", None) in MEMORIES
        return [
            type(value).__name__,
            [
                [f.name, _plain(getattr(value, f.name), memory)]
                for f in dataclasses.fields(value)
                if f.name not in POSITIONS
            ],
        ]
    if isinstance(value, dict):
        return [[str(k), _plain(v, memory)] for k, v in value.items()]
    if isinstance(value, (list, tuple)):
        return [
            _plain(v, memory)
            for v in value
            if not (memory and getattr(v, "name", None) == "id" and hasattr(v, "type"))
        ]
    return repr(value)


def _sample(variable, ids: bool = False):
    """A value of the type that a variable declares (and of its fields).

    The field ``id`` of a memory item is left out unless ``ids``: templates that did not declare it
    before are given the same values as before.
    """
    fields = {
        f.name: _sample(f, ids)
        for f in (getattr(variable, "fields", None) or [])
        if ids or f.name != "id"
    }
    if variable.type == "number":
        return 3
    if variable.type == "bool":
        return True
    if variable.type == "map":
        return fields
    if variable.type == "list":
        item = getattr(variable, "item_type", None)
        value = fields or {"number": 3, "bool": True, "map": {}}.get(item, "a")
        if ids and isinstance(value, dict) and variable.name in MEMORIES:
            value = {**value, "id": "m1"}
        return [value, value]
    return "sample"


def _variable_sets(spec) -> dict[str, dict]:
    sets: dict[str, dict] = {
        "empty": {},
        "full": {v.name: _sample(v) for v in spec.variables},
        "system": {"system_prompt": "SYS"},
        "ids": {v.name: _sample(v, True) for v in spec.variables},
    }
    for v in spec.variables:  # each shared variable alone: its text must not need another variable
        if v.name in SHARED:
            sets["only_" + v.name] = {v.name: _sample(v)}
    return sets


def _render(builder: BasePromptBuilder, stem: str, variables: dict, as_name: str | None = None) -> list:
    try:
        return [[m.role, m.content] for m in builder.render(stem, variables)]
    except Exception as error:  # the same mistake before and after is the same result
        text = str(error)
        return [type(error).__name__, text.replace(stem, as_name) if as_name else text]


def _digest(text) -> str:
    return hashlib.sha256(json.dumps(text).encode()).hexdigest()


def _renders(builder: BasePromptBuilder, stem: str, as_name: str | None = None) -> dict[str, list]:
    """The renderings of a template; a mistake names the template, and ``as_name`` is the name it had."""
    spec = builder._entry(builder._latest_key(stem)).spec
    return {label: _render(builder, stem, v, as_name) for label, v in _variable_sets(spec).items()}


def _heads(builder: BasePromptBuilder, stem: str, as_name: str | None = None) -> str:
    spec = builder._entry(builder._latest_key(stem)).spec
    by_name = dataclasses.replace(
        spec,
        name=as_name or spec.name,  # a renamed template is compared under the name it had
        parts=(),
        variables=sorted(spec.variables, key=lambda v: v.name),
    )
    return _digest(_plain(by_name))


def _from_folder(folder: Path) -> BasePromptBuilder:
    """A builder that compiled the templates of ``folder`` (flat files, no include)."""
    builder = BasePromptBuilder()
    for path in sorted(folder.glob("*.skye")):
        key = builder._latest_key(path.stem)
        builder._pending.pop(key, None)
        builder._entries[key] = messages._compile_skye(
            path.stem, path.read_text(encoding="utf-8"), str(path)
        )
    return builder


def write_fixture(folder: Path) -> None:
    """Make ``fixtures/templates_before.json``: ``before`` from ``folder``, ``after`` from the templates now."""
    old, new = _from_folder(folder), BasePromptBuilder()
    before, after = {}, {}
    for stem in sorted(p.stem for p in folder.glob("*.skye")):
        if stem in REMOVED:
            continue
        renders = _renders(old, stem)
        before[stem] = {"heads": _heads(old, stem), **{k: _digest(v) for k, v in renders.items()}}
        now = _renders(new, NEW_NAME[stem], stem)
        for label in CHANGES.get(stem, ((), ""))[0]:
            after[f"{stem}/{label}"] = {
                "digest": _digest(now[label]),
                **({"text": now[label]} if label.startswith("only_") else {}),
            }
    FIXTURE.write_text(
        json.dumps({"before": before, "after": after}, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


DATA = json.loads(FIXTURE.read_text(encoding="utf-8"))
BEFORE, AFTER = DATA["before"], DATA["after"]
LABELS = ("empty", "full", "system", "ids")
OLD_NAMES = sorted(n for n in BEFORE if n not in REMOVED)  # the names of the fixture that are still templates


def test_the_fixture_has_the_forty_templates_and_the_catalogue_has_the_renamed_ones():
    bundled = sorted(p.stem for p in loaders.TEMPLATES_DIR.glob("*.skye"))
    on_disk = sorted({*bundled, *(p.stem for p in GALLERY_DIR.glob("*.skye"))} - {"extraction_generic"})
    assert len(BEFORE) == 40
    assert sorted(set(BEFORE) - set(REMOVED)) == sorted(NEW_NAME)  # every other one was renamed or kept
    assert on_disk == sorted(NEW_NAME.values())
    assert sorted(loaders.bundled_names()) == bundled  # no partial is listed as a template
    assert not set(REMOVED) & set(on_disk)


@pytest.mark.parametrize("name", OLD_NAMES)
def test_a_template_declares_what_it_declared_before_the_move(name):
    assert _heads(gallery_builder(), NEW_NAME[name], as_name=name) == BEFORE[name]["heads"]


@pytest.mark.parametrize("name", OLD_NAMES)
def test_a_template_renders_as_it_did_before_the_move_except_for_the_listed_changes(name):
    renders = _renders(gallery_builder(), NEW_NAME[name], name)
    changed = set(CHANGES.get(name, ((), ""))[0])
    for label, rendered in renders.items():
        if label in changed or label == "ids":
            continue
        assert _digest(rendered) == BEFORE[name][label], f"{name}: the rendering {label!r} changed"
    for label in changed:
        assert _digest(renders[label]) == AFTER[f"{name}/{label}"]["digest"], f"{name}/{label}"
        assert (
            _digest(renders[label]) != BEFORE[name][label]
        ), f"{name}/{label} is listed but did not change"


def test_every_listed_change_has_its_new_text_in_the_fixture():
    listed = {f"{n}/{label}" for n, (labels, _) in CHANGES.items() for label in labels}
    assert listed == set(AFTER)
    assert all(AFTER[k]["text"] for k in AFTER if k.split("/")[1].startswith("only_"))


@pytest.mark.parametrize("name", OLD_NAMES)
def test_an_item_with_an_id_shows_it_and_a_template_that_kept_its_section_renders_as_before(name):
    builder = gallery_builder()
    shown = _renders(builder, NEW_NAME[name], name)["ids"]
    text = template_path(NEW_NAME[name]).read_text(encoding="utf-8")
    section_from_the_partial = text.count("use memories") >= 2  # in variables and in its message
    if section_from_the_partial:
        assert "[m1]" in json.dumps(shown)  # the standard section shows the id of an item
    elif (
        name not in CHANGES
    ):  # no section of memories, or its own section (KEEP_THE_SECTION): as before
        assert _digest(shown) == BEFORE[name]["ids"]
    if name in KEEP_THE_SECTION:
        assert "[m1]" in json.dumps(shown)  # their own section shows the id, as it did


def test_the_templates_that_use_a_partial_say_so_and_the_partials_are_not_templates():
    folder = loaders.TEMPLATES_DIR
    partials = sorted((folder / "common").glob("*.skye"))
    assert [p.name for p in partials] == [
        "memories.skye",
        "system_prompt.skye",
        "tools.skye",
    ]
    assert all("partial = true" in p.read_text(encoding="utf-8") for p in partials)
    users = [p.stem for p in folder.glob("*.skye") if 'include "common/' in p.read_text("utf-8")]
    assert len(users) == 11  # every bundled template takes the system prompt of the shared part
