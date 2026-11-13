"""Tests for the bundled smolagents-style `.skye` prompts.

Covers the code agent, the tool-calling agent, the planning step and the managed agent.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from skye.base.dsl import build
from skye.base.messages import SkyeMessage
from skye.prompts.skye_prompts import load_prompt, render_prompt
from tests.unit.prompts.bundled import build_template, load_template, template_path

NAMES = ["agent_smol_code", "agent_react", "agent_smol_planning", "agent_smol_managed"]

TOOLS = [
    {
        "name": "web_search",
        "description": "Search the web for a query.",
        "parameters": {"query": "the text to search for", "limit": "integer"},
        "returns": "a list of results",
    },
    {"name": "clock", "description": "Return the current time."},
]

MEMORY: dict[str, list[dict[str, Any]]] = {
    "episodic_memory": [{"content": "Asked about trains to Turin", "timestamp": "2026-10-01"}],
    "semantic_memory": [{"content": "Turin is in Piedmont", "source": "atlas", "name": "geo"}],
    "procedural_memory": [{"name": "Book a ticket", "steps": ["pick a train", "pay online"]}],
    "persona_memory": [{"content": "The user prefers short answers"}],
    "working_memory": [{"content": "The budget is 50 euros"}],
}

MEMORY_HEADINGS = [
    "## Memory",
    "### Persona",
    "### Known facts",
    "### Past events",
    "### Procedures",
    "### Current notes",
]  # the standard headings of common/memories.skye (task 24.6)


def _spec(name: str) -> Any:
    return load_template(template_path(name), name)


def _render(name: str, variables: dict[str, Any], history: Any = None) -> list[SkyeMessage]:
    return render_prompt(_spec(name), variables, history=history)


def _roles(messages: list[SkyeMessage]) -> list[str]:
    return [m.role for m in messages]


def _system(messages: list[SkyeMessage]) -> str:
    return messages[0].content


# -- every prompt -------------------------------------------------------------------------------


@pytest.mark.parametrize("name", NAMES)
def test_has_front_matter(name: str) -> None:
    metadata = build_template(template_path(name)).metadata
    assert metadata["title"] and metadata["description"]
    assert metadata["version"] == "1.0"
    assert isinstance(metadata["tags"], list) and metadata["tags"]


@pytest.mark.parametrize("name", NAMES)
def test_minimal_render_has_system_and_user(name: str) -> None:
    messages = _render(name, {"task": "Find a cheap train to Turin."})
    assert _roles(messages) == ["system", "user"]
    assert "Find a cheap train to Turin." in messages[-1].content
    text = "\n".join(m.content for m in messages)
    assert "## Tools" not in text
    assert "## Memory" not in text
    assert "{{" not in text and "{%" not in text


@pytest.mark.parametrize("name", NAMES)
def test_task_is_required(name: str) -> None:
    with pytest.raises(ValueError, match="task"):
        _render(name, {})


@pytest.mark.parametrize("name", NAMES)
def test_tools_and_every_memory_type(name: str) -> None:
    messages = _render(name, {"task": "Plan a trip.", "tools": TOOLS, **MEMORY})
    system = _system(messages)
    assert "## Tools" in system
    assert "`web_search`: Search the web for a query." in system
    # Decision D80: the parameters as JSON Schema, as in every other agent prompt.
    assert 'Parameters: {"query": "the text to search for", "limit": "integer"}' in system
    assert "`query`:" not in system
    assert "Returns: a list of results" in system
    assert "`clock`: Return the current time." in system
    for heading in MEMORY_HEADINGS:
        assert heading in system, heading
    assert "- [2026-10-01] Asked about trains to Turin" in system
    assert "- Turin is in Piedmont (source: atlas)" in system  # the standard line: the name of a fact is not shown
    assert "- Book a ticket" in system and "  * pay online" in system
    assert "- The user prefers short answers" in system
    assert "- The budget is 50 euros" in system


@pytest.mark.parametrize("name", NAMES)
def test_only_non_empty_memory_types_render(name: str) -> None:
    messages = _render(name, {"task": "t", "working_memory": [{"content": "note"}]})
    system = _system(messages)
    assert "## Memory" in system
    assert "### Current notes" in system
    for heading in MEMORY_HEADINGS[1:-1]:
        assert heading not in system


@pytest.mark.parametrize("name", NAMES)
def test_history_placeholder(name: str) -> None:
    history = [
        {"role": "user", "content": "earlier question"},
        {"role": "assistant", "content": "earlier answer"},
    ]
    messages = _render(name, {"task": "t"}, history={"history": history})
    assert _roles(messages) == ["system", "user", "assistant", "user"]
    assert messages[1].content == "earlier question"
    assert messages[2].content == "earlier answer"


@pytest.mark.parametrize("name", NAMES)
def test_system_prompt_overrides_role_sentence(name: str) -> None:
    default = _system(_render(name, {"task": "t"})).splitlines()[0]
    system = _system(_render(name, {"task": "t", "system_prompt": "You are Bob."}))
    assert system.startswith("You are Bob.")
    assert default not in system


# -- code agent ---------------------------------------------------------------------------------


def test_code_agent_without_tools_mentions_only_final_answer() -> None:
    system = _system(_render("agent_smol_code", {"task": "t"}))
    assert "Thought:" in system and "Code:" in system and "Observation:" in system
    assert "final_answer(" in system
    assert "no tools apart from `final_answer(answer)`" in system
    assert "Example with a tool" not in system
    assert "Import only modules from the Python standard library." in system


def test_code_agent_with_tools_imports_team_and_instructions() -> None:
    system = _system(
        _render(
            "agent_smol_code",
            {
                "task": "t",
                "tools": TOOLS,
                "authorized_imports": ["math", "statistics"],
                "managed_agents": [{"name": "researcher", "description": "Finds sources."}],
                "instructions": "Answer in Italian.",
            },
        )
    )
    assert "Example with a tool" in system
    assert "- `final_answer(answer)`" in system
    assert "no tools apart from" not in system
    assert "You may import only these modules: math, statistics." in system
    assert "## Team members" in system and "- `researcher`: Finds sources." in system
    assert "## Additional instructions\nAnswer in Italian." in system


# -- tool-calling agent -------------------------------------------------------------------------


def test_tool_calling_agent_uses_json_actions() -> None:
    system = _system(_render("agent_react", {"task": "t"}))
    assert "Action:" in system
    assert '{"name": "final_answer", "arguments": {"answer":' in system
    assert "no tools apart from `final_answer`" in system
    with_tools = _system(_render("agent_react", {"task": "t", "tools": TOOLS}))
    assert "- `final_answer`: ends the task" in with_tools
    assert "no tools apart from" not in with_tools


# -- planning -----------------------------------------------------------------------------------


def test_planning_initial_phase_is_the_default() -> None:
    user = _render("agent_smol_planning", {"task": "t"})[-1].content
    assert "## 1. Facts" in user and "## 2. Plan" in user
    assert "<end_plan>" in user
    assert "Updated facts" not in user


def test_planning_update_phase() -> None:
    messages = _render(
        "agent_smol_planning",
        {"task": "t", "phase": "update", "previous_plan": "1. Search trains", "remaining_steps": 4},
        history={"history": [{"role": "assistant", "content": "step 1 done"}]},
    )
    assert _roles(messages) == ["system", "assistant", "user"]
    user = messages[-1].content
    assert "## 1. Updated facts" in user and "## 2. New plan" in user
    assert "## Previous plan\n1. Search trains" in user
    assert "at most 4 steps left" in user
    assert "## 1. Facts\n" not in user


def test_planning_update_without_optional_parts() -> None:
    user = _render("agent_smol_planning", {"task": "t", "phase": "update"})[-1].content
    assert "Previous plan" not in user
    assert "steps left" not in user


# -- managed agent ------------------------------------------------------------------------------


def test_managed_agent_report_layout_and_names() -> None:
    messages = _render(
        "agent_smol_managed",
        {
            "task": "Check the timetable.",
            "name": "scout",
            "manager": "the travel planner",
            "additional_context": "Weekdays only.",
        },
    )
    assert messages[0].content.startswith("You are scout, an agent")
    user = messages[-1].content
    assert user.startswith("Task from the travel planner:\nCheck the timetable.")
    assert "## Additional context\nWeekdays only." in user
    for heading in ("### 1. Short answer", "### 2. Detailed answer", "### 3. Additional context"):
        assert heading in user


def test_managed_agent_defaults() -> None:
    messages = _render("agent_smol_managed", {"task": "t"})
    assert messages[0].content.startswith("You are an agent working as a member of a team.")
    assert messages[-1].content.startswith("Task from your manager:")
    assert "## Additional context" not in messages[-1].content


@pytest.mark.parametrize("name", NAMES)
def test_tool_parameters_are_shown_as_json_schema(name: str) -> None:
    schema = {
        "type": "object",
        "properties": {"unit": {"type": "string", "enum": ["c", "f"], "default": "c"}},
        "required": ["unit"],
    }
    tool = {"name": "weather", "description": "Weather now.", "parameters": schema}
    system = _system(_render(name, {"task": "t", "tools": [tool]}))
    assert f"Parameters: {json.dumps(schema)}" in system
    text = (template_path(name)).read_text(encoding="utf-8")
    assert "each param in tool.parameters" not in text
