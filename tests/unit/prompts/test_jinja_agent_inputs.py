"""agent_form, agent_multimodal and agent_tool (the last three converted from ``.jinja``) accept optional tools and memories of every kind."""

from __future__ import annotations

from typing import Any

import pytest

from skye.prompts.messages import BasePromptBuilder
from tests.unit.prompts.bundled import gallery_builder

NAMES = ("agent_form", "agent_multimodal", "agent_tool")
MEMORY_VARS = (
    "persona_memory",
    "episodic_memory",
    "semantic_memory",
    "procedural_memory",
    "working_memory",
)

TOOLS = [
    {
        "name": "search",
        "description": "Search the web",
        "parameters": {"q": "str"},
        "returns": "hits",
    },
    {"name": "calc", "description": "Do arithmetic"},
]
MEMORIES: dict[str, Any] = {
    "persona_memory": [{"content": "Speaks formally", "source": "profile"}, {"content": "Brief"}],
    "episodic_memory": [{"content": "Asked about invoices", "timestamp": "2026-01-02"}],
    "semantic_memory": [{"content": "Paris is in France", "source": "atlas"}],
    "procedural_memory": [
        {"name": "Refund", "content": "How to refund", "steps": ["check", "pay"]}
    ],
    "working_memory": [
        {"name": "goal", "content": "close the ticket"},
        {"content": "user is waiting"},
    ],
}


def _base(name: str) -> dict[str, Any]:
    # agent_tool always lists its actions, so it needs a tools list even in the baseline.
    return {"input": "hello", "tools": TOOLS} if name == "agent_tool" else {"input": "hello"}


def _system(messages: list[Any]) -> str:
    return "\n".join(m.content for m in messages if m.role == "system")


@pytest.fixture
def builder() -> BasePromptBuilder:
    return gallery_builder()


@pytest.mark.parametrize("name", NAMES)
def test_new_inputs_are_optional(builder: BasePromptBuilder, name: str) -> None:
    optional = set(builder.get_template_metadata(name)["optional_variables"])
    assert set(MEMORY_VARS) <= optional
    if name != "agent_tool":
        assert "tools" in optional


@pytest.mark.parametrize("name", NAMES)
def test_sections_render_with_tools_and_memories(builder: BasePromptBuilder, name: str) -> None:
    variables = {**_base(name), "tools": TOOLS, **MEMORIES}
    system = _system(builder.render(name, variables))

    assert "## Memory" in system
    for heading in (
        "### Persona",
        "### Past events",
        "### Known facts",
        "### Procedures",
        "### Current notes",
    ):
        assert heading in system
    assert "- Speaks formally (source: profile)" in system
    assert "- Brief" in system
    assert "- [2026-01-02] Asked about invoices" in system
    assert "- Paris is in France (source: atlas)" in system
    assert "- Refund\n  How to refund\n  * check\n  * pay" in system
    assert "- goal: close the ticket\n- user is waiting" in system

    if name == "agent_tool":
        # Its own action list is the tool rendering; no duplicate section.
        assert "## Tools" not in system
        assert '- "search": Search the web' in system
    else:
        assert "## Tools" in system
        assert "- **search**: Search the web" in system
        assert 'Parameters: {"q": "str"}' in system
        assert "Returns: hits" in system
        assert "- **calc**: Do arithmetic" in system


@pytest.mark.parametrize("name", NAMES)
def test_sections_absent_without_inputs(builder: BasePromptBuilder, name: str) -> None:
    variables = _base(name)
    if name == "agent_tool":
        empty = {k: [] for k in MEMORY_VARS}
    else:
        empty = {"tools": [], **{k: [] for k in MEMORY_VARS}}
    for extra in ({}, empty):
        messages = builder.render(name, {**variables, **extra})
        text = "\n".join(m.content for m in messages)
        assert "## Tools" not in text
        assert "## Memory" not in text


@pytest.mark.parametrize("name", NAMES)
def test_only_some_memory_kinds(builder: BasePromptBuilder, name: str) -> None:
    system = _system(
        builder.render(name, {**_base(name), "semantic_memory": MEMORIES["semantic_memory"]})
    )
    assert "## Memory\n### Known facts\n- Paris is in France (source: atlas)" in system
    assert "### Persona" not in system
    assert "### Procedures" not in system
