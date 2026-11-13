"""Every agent prompt accepts an optional tool list and optional memories of every kind."""

from __future__ import annotations

from typing import Any

import pytest

from skye.base.dsl import PromptSpec
from skye.base.messages import SkyeMessage, SystemMessage
from skye.prompts.skye_prompts import load_prompt, render_prompt
from tests.unit.prompts.bundled import BUNDLED_DIR, GALLERY_DIR, load_template, template_path

AGENT_VARIABLES = (
    "tools",
    "episodic_memory",
    "semantic_memory",
    "procedural_memory",
    "persona_memory",
    "working_memory",
)

# The converted agent templates that gained the tools and memory inputs.
CONVERTED = ("agent_code", "agent_memory_assistant", "agent_memory_recall", "agent_procedure", "agent_reasoning")

# Templates that render ``episodic_memory`` or ``semantic_memory`` in a section of their own: none since
# task 24.6, every template takes the standard section of common/memories.skye.
OWN_EPISODIC: dict[str, str] = {}
OWN_SEMANTIC: dict[str, str] = {}

# Templates that render ``procedural_memory`` (formerly ``procedural_memories`` / ``procedures``)
# in their own section: the heading and the lines of the two procedures of MEMORY.
OWN_PROCEDURAL = {
    "agent_procedure": (
        "You have access to the following procedures:",
        '- "report_procedure": \n  * collect sources\n  * draft\n  * review',
        '- "style_check": Read the draft aloud.',
    ),
}

TOOLS = [
    {
        "name": "web_search",
        "description": "Searches the web.",
        "parameters": {"query": {"type": "string"}},
        "returns": "a list of links",
    },
    {"name": "clock", "description": "Gives the current time."},
]

MEMORY: dict[str, list[dict[str, Any]]] = {
    "episodic_memory": [{"content": "Asked for a short report.", "timestamp": "2026-11-01"}],
    "semantic_memory": [{"content": "Solar capacity doubled since 2020.", "source": "IEA"}],
    "procedural_memory": [
        {"name": "report_procedure", "steps": ["collect sources", "draft", "review"]},
        {"name": "style_check", "content": "Read the draft aloud."},
    ],
    "persona_memory": [{"content": "Prefers concise answers."}],
    "working_memory": [{"name": "deadline", "content": "Friday"}],
}


def _all_agent_templates() -> list[str]:
    paths = [*BUNDLED_DIR.glob("*.skye"), *GALLERY_DIR.glob("*.skye")]
    return sorted(path.stem for path in paths if path.stem.startswith("agent_"))


def _spec(name: str) -> PromptSpec:
    return load_template(template_path(name), name)


def _system(messages: list[SkyeMessage]) -> str:
    return next(m.content for m in messages if isinstance(m, SystemMessage))


@pytest.mark.parametrize("name", CONVERTED)
def test_tools_and_every_memory_kind_render(name: str) -> None:
    system = _system(render_prompt(_spec(name), {"input": "Hi", "tools": TOOLS, **MEMORY}))
    assert "## Tools" in system
    assert "You may call these tools when they help; when a tool would not help, answer without it." in system
    assert "- **web_search**: Searches the web." in system
    assert 'Parameters: {"query": {"type": "string"}}' in system
    assert "Returns: a list of links" in system
    assert "- **clock**: Gives the current time." in system

    assert "## Memory" in system
    assert "### Persona" in system
    assert "- Prefers concise answers." in system
    if name in OWN_SEMANTIC:
        assert OWN_SEMANTIC[name] in system
        assert "  - Solar capacity doubled since 2020. (extracted from IEA)" in system
        assert "### Known facts" not in system
        assert system.count("Solar capacity doubled since 2020.") == 1
    else:
        assert "### Known facts" in system
        assert "- Solar capacity doubled since 2020. (source: IEA)" in system

    if name in OWN_PROCEDURAL:
        for part in OWN_PROCEDURAL[name]:
            assert part in system
        assert "### Procedures" not in system
        assert system.count("Read the draft aloud.") == 1
    else:
        assert "### Procedures" in system
        assert "- report_procedure" in system
        assert "  * draft" in system
        assert "  Read the draft aloud." in system
    assert "### Current notes" in system
    assert "- deadline: Friday" in system

    if name in OWN_EPISODIC:
        # Rendered once, by the pre-existing section.
        assert OWN_EPISODIC[name] in system
        assert "### Past events" not in system
        assert system.count("Asked for a short report.") == 1
    else:
        assert "### Past events" in system
        assert "- [2026-11-01] Asked for a short report." in system


@pytest.mark.parametrize("name", CONVERTED)
def test_without_tools_and_memory_no_sections(name: str) -> None:
    system = _system(render_prompt(_spec(name), {"input": "Hi"}))
    assert "## Tools" not in system
    assert "## Memory" not in system


@pytest.mark.parametrize("name", _all_agent_templates())
def test_agent_variables_exist_and_are_optional(name: str) -> None:
    variables = {v.name: v for v in _spec(name).variables}
    for variable in AGENT_VARIABLES:
        assert variable in variables, f"{name} lacks {variable}"
        assert not variables[variable].required, f"{name}.{variable} is required"
