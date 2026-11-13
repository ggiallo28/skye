"""Tests for the bundled memory-maintenance prompts (update, consolidation, working memory)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from skye.base.dsl import PromptSpec, build
from skye.base.messages import AssistantMessage, SkyeMessage, SystemMessage, UserMessage
from skye.prompts.skye_prompts import load_prompt, render_prompt
from tests.unit.prompts.bundled import build_template, load_template, template_path


NAMES = ("agent_memory_update", "agent_memory_consolidation", "agent_memory_working")

REQUIRED: dict[str, dict[str, Any]] = {
    "agent_memory_update": {},
    "agent_memory_consolidation": {},
    "agent_memory_working": {"task": "Write the quarterly report."},
}

TOOLS = [
    {
        "name": "web_search",
        "description": "Searches the web.",
        "parameters": {"query": {"type": "string"}},
        "returns": "a list of links",
    },
]

MEMORY: dict[str, list[dict[str, Any]]] = {
    "persona_memory": [
        {"id": "p1", "content": "Prefers concise answers.", "source": "chat"},
        {"content": "Lives in Turin."},
    ],
    "episodic_memory": [
        {"id": "e1", "content": "Asked for a short report.", "timestamp": "2026-11-01"},
        {"content": "Said hello.", "timestamp": "2026-11-02"},
    ],
    "semantic_memory": [
        {"id": "s1", "content": "Solar capacity doubled since 2020.", "source": "IEA"},
        {"id": "s2", "content": "The team uses Python."},
    ],
    "procedural_memory": [
        {"id": "r1", "name": "report_procedure", "steps": ["collect sources", "draft"]},
        {"id": "r2", "content": "Read the draft aloud."},
        {"name": "style_check"},
    ],
    "working_memory": [
        {"id": "w1", "name": "deadline", "content": "Friday"},
        {"id": "w2", "content": "Use the blue template."},
        {"content": "Ask about the logo."},
    ],
}


def _spec(name: str) -> PromptSpec:
    return load_template(template_path(name), name)


def _render(
    name: str, history: list[SkyeMessage] | None = None, **variables: Any
) -> list[SkyeMessage]:
    return render_prompt(
        _spec(name), {**REQUIRED[name], **variables}, history={"history": history or []}
    )


def _system(messages: list[SkyeMessage]) -> str:
    return next(m.content for m in messages if isinstance(m, SystemMessage))


def _json_lines(text: str) -> list[Any]:
    """Every line of ``text`` that is a JSON object, parsed."""
    return [json.loads(line) for line in text.splitlines() if line.startswith("{")]


# -- common -------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", NAMES)
def test_has_front_matter(name: str) -> None:
    metadata = build_template(template_path(name)).metadata
    assert metadata["title"] and metadata["description"]
    assert metadata["version"] == "1.0"
    assert isinstance(metadata["tags"], list) and metadata["tags"]


@pytest.mark.parametrize("name", NAMES)
def test_roles_are_system_then_user(name: str) -> None:
    messages = _render(name)
    assert [m.role for m in messages] == ["system", "user"]


@pytest.mark.parametrize("name", NAMES)
def test_history_is_inserted_between_system_and_user(name: str) -> None:
    history: list[SkyeMessage] = [
        UserMessage(content="I moved to Milan."),
        AssistantMessage(content="Noted."),
    ]
    messages = _render(name, history=history)
    assert [m.role for m in messages] == ["system", "user", "assistant", "user"]
    assert messages[1].content == "I moved to Milan."
    assert messages[2].content == "Noted."


@pytest.mark.parametrize("name", NAMES)
def test_no_memories_no_sections(name: str) -> None:
    system = _system(_render(name))
    assert "## Memory" not in system
    assert "## Tools" not in system
    assert "### " not in system


@pytest.mark.parametrize("name", NAMES)
def test_tools_section(name: str) -> None:
    system = _system(_render(name, tools=TOOLS))
    assert "## Tools" in system
    assert "- **web_search**: Searches the web." in system
    assert 'Parameters: {"query": {"type": "string"}}' in system
    assert "Returns: a list of links" in system


@pytest.mark.parametrize("name", NAMES)
def test_every_memory_kind_with_ids(name: str) -> None:
    system = _system(_render(name, **MEMORY))
    assert "## Memory" in system
    assert "### Persona" in system
    assert "- [p1] Prefers concise answers. (source: chat)" in system
    assert "- Lives in Turin." in system
    assert "### Past events" in system
    assert "- [e1] Asked for a short report. (at 2026-11-01)" in system
    assert "- [2026-11-02] Said hello." in system  # no id: the standard line of every template
    assert "### Known facts" in system
    assert "- [s1] Solar capacity doubled since 2020. (source: IEA)" in system
    assert "- [s2] The team uses Python." in system
    assert "### Procedures" in system
    assert "- [r1] report_procedure" in system
    assert "  * collect sources" in system
    assert "- [r2]\n  Read the draft aloud." in system
    assert "- style_check" in system
    assert "### Current notes" in system
    assert "- [w1] deadline: Friday" in system
    assert "- [w2] Use the blue template." in system
    assert "- Ask about the logo." in system


@pytest.mark.parametrize("kind", sorted(MEMORY))
def test_one_memory_kind_alone(kind: str) -> None:
    system = _system(_render("agent_memory_update", **{kind: MEMORY[kind]}))
    assert "## Memory" in system
    assert system.count("### ") == 1


@pytest.mark.parametrize("name", NAMES)
def test_system_prompt_overrides_the_role_sentence(name: str) -> None:
    default = _system(_render(name))
    custom = _system(_render(name, system_prompt="You are the archivist."))
    assert custom.startswith("You are the archivist.")
    assert default.splitlines()[0] not in custom


@pytest.mark.parametrize("name", NAMES)
def test_json_examples_parse(name: str) -> None:
    system = _system(_render(name))
    assert len(_json_lines(system)) == 1  # the example
    empty = next(
        line for line in system.splitlines() if line.startswith("When ") and "reply {" in line
    )
    answer = json.loads(empty[empty.index("{") : -1])  # the empty answer, without the final dot
    assert all(value == [] for value in answer.values())


# -- agent_memory_update ------------------------------------------------------------------------


def test_update_json_shape_and_rules() -> None:
    system = _system(_render("agent_memory_update"))
    for field in ('"op"', '"kind"', '"id"', '"content"', '"name"', '"steps"', '"reason"'):
        assert field in system
    for word in ('"add"', '"update"', '"delete"', '"none"'):
        assert word in system
    assert 'reply {"operations": []}' in system
    example = _json_lines(system)[0]
    assert {op["op"] for op in example["operations"]} <= {"add", "update", "delete", "none"}
    assert "secrets" in system
    assert "atomic" in system


def test_update_kinds_and_limit() -> None:
    plain = _system(_render("agent_memory_update"))
    assert "Only propose operations for these kinds" not in plain
    assert "at most" not in plain
    system = _system(
        _render("agent_memory_update", kinds=["semantic", "persona"], max_operations=5)
    )
    assert "Only propose operations for these kinds: semantic, persona." in system
    assert "Propose at most 5 operations" in system


def test_update_names() -> None:
    system = _system(_render("agent_memory_update", user_name="Ada", agent_name="Skye"))
    assert "called Skye" in system
    assert "called Ada" in system


def test_update_transcript_latest_exchange_and_time() -> None:
    user = _render(
        "agent_memory_update",
        transcript=[
            {"speaker": "user", "content": "I switched to Rust."},
            {"speaker": "assistant", "content": "Good choice."},
        ],
        latest_exchange="user: please forget my old address",
        timestamp="2026-11-08 10:00",
    )[-1].content
    assert "## Conversation" in user
    assert "user: I switched to Rust.\nassistant: Good choice." in user
    assert "## Latest exchange" in user
    assert "please forget my old address" in user
    assert "Current time: 2026-11-08 10:00" in user
    assert "messages above" not in user


def test_update_without_transcript_points_at_history() -> None:
    user = _render("agent_memory_update")[-1].content
    assert "## Conversation" not in user
    assert "messages above" in user


# -- agent_memory_consolidation -----------------------------------------------------------------


def test_consolidation_json_shape_and_merge() -> None:
    system = _system(_render("agent_memory_consolidation", **MEMORY))
    assert '"merge"' in system
    assert '"ids"' in system
    example = _json_lines(system)[0]
    merge = next(op for op in example["operations"] if op["op"] == "merge")
    assert isinstance(merge["ids"], list)
    assert "newer" in system


def test_consolidation_user_message() -> None:
    empty = _render("agent_memory_consolidation")[-1].content
    assert '{"operations": []}' in empty
    full = _render("agent_memory_consolidation", **MEMORY)[-1].content
    assert "Consolidate the memories" in full


def test_consolidation_kinds() -> None:
    system = _system(_render("agent_memory_consolidation", kinds=["episodic"]))
    assert "Only propose operations for these kinds: episodic." in system


# -- agent_memory_working -----------------------------------------------------------------------


def test_working_requires_task() -> None:
    with pytest.raises(ValueError) as info:
        render_prompt(_spec("agent_memory_working"), {})
    assert "task" in str(info.value)


def test_working_json_shape_and_task() -> None:
    messages = _render("agent_memory_working", latest_exchange="user: the deadline moved to Monday")
    system, user = messages[0].content, messages[-1].content
    example = _json_lines(system)[0]
    assert set(example) == {"notes", "done", "open_questions"}
    assert "## Task\nWrite the quarterly report." in user
    assert "the deadline moved to Monday" in user
    assert "messages above" not in user
