"""Tests for the bundled supervisor prompts (router, planner, reviewer, hierarchical)."""

from __future__ import annotations

from typing import Any

import pytest

from skye.base.dsl import PromptSpec, build
from skye.base.messages import AssistantMessage, SkyeMessage, SystemMessage, UserMessage
from skye.prompts.skye_prompts import load_prompt, render_prompt
from tests.unit.prompts.bundled import build_template, load_template, template_path


NAMES = (
    "agent_supervisor_router",
    "agent_supervisor_planner",
    "agent_supervisor_reviewer",
    "agent_supervisor_hierarchical",
)

# The variables each prompt cannot do without.
REQUIRED: dict[str, dict[str, Any]] = {
    "agent_supervisor_router": {"task": "Write a market report on solar panels."},
    "agent_supervisor_planner": {"task": "Write a market report on solar panels."},
    "agent_supervisor_reviewer": {
        "task": "Write a market report on solar panels.",
        "worker_name": "writer",
        "worker_output": "Solar is growing.",
    },
    "agent_supervisor_hierarchical": {"task": "Launch a new product."},
}

WORKERS = [
    {
        "name": "researcher",
        "description": "Finds sources on the web.",
        "skills": ["search", "reading"],
    },
    {"name": "writer", "description": "Writes clear prose."},
]

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
    "episodic_memory": [
        {"content": "The user asked for a short report last week.", "timestamp": "2026-11-01"}
    ],
    "semantic_memory": [{"content": "Solar capacity doubled since 2020.", "source": "IEA"}],
    "procedural_memory": [
        {"name": "report_procedure", "steps": ["collect sources", "draft", "review"]},
        {"name": "style_check", "content": "Read the draft aloud."},
    ],
    "persona_memory": [{"content": "Prefers concise answers."}],
    "working_memory": [{"name": "deadline", "content": "Friday"}],
}

PROGRESS = [{"worker": "researcher", "summary": "Collected ten sources."}]


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


# -- common to every supervisor ----------------------------------------------------------------


@pytest.mark.parametrize("name", NAMES)
def test_has_front_matter(name: str) -> None:
    metadata = build_template(template_path(name)).metadata
    assert metadata["title"] and metadata["description"]
    assert metadata["version"] == "1.0"
    assert isinstance(metadata["tags"], list) and metadata["tags"]


@pytest.mark.parametrize("name", NAMES)
def test_roles_are_system_then_user(name: str) -> None:
    messages = _render(name)
    assert isinstance(messages[0], SystemMessage)
    assert isinstance(messages[-1], UserMessage)
    assert len(messages) == 2


@pytest.mark.parametrize("name", NAMES)
def test_missing_required_variable_raises(name: str) -> None:
    with pytest.raises(ValueError) as info:
        render_prompt(_spec(name), {})
    for variable in REQUIRED[name]:
        assert variable in str(info.value)


@pytest.mark.parametrize("name", NAMES)
def test_history_is_inserted_between_system_and_user(name: str) -> None:
    history: list[SkyeMessage] = [
        UserMessage(content="earlier question"),
        AssistantMessage(content="earlier answer"),
    ]
    messages = _render(name, history=history)
    assert [m.role for m in messages] == ["system", "user", "assistant", "user"]
    assert messages[1].content == "earlier question"
    assert messages[2].content == "earlier answer"


@pytest.mark.parametrize("name", NAMES)
def test_without_tools_and_memory_no_sections(name: str) -> None:
    system = _system(_render(name))
    assert "## Tools" not in system
    assert "## Memory" not in system


@pytest.mark.parametrize("name", NAMES)
def test_tools_section(name: str) -> None:
    system = _system(_render(name, tools=TOOLS))
    assert "## Tools" in system
    assert "- **web_search**: Searches the web." in system
    assert 'Parameters: {"query": {"type": "string"}}' in system
    assert "Returns: a list of links" in system
    assert "- **clock**: Gives the current time." in system


@pytest.mark.parametrize("name", NAMES)
def test_every_memory_type(name: str) -> None:
    system = _system(_render(name, **MEMORY))
    assert "## Memory" in system
    assert "### Past events" in system
    assert "- [2026-11-01] The user asked for a short report last week." in system
    assert "### Known facts" in system
    assert "- Solar capacity doubled since 2020. (source: IEA)" in system
    assert "### Procedures" in system
    assert "- report_procedure" in system
    assert "  * draft" in system
    assert "  Read the draft aloud." in system
    assert "### Persona" in system
    assert "- Prefers concise answers." in system
    assert "### Current notes" in system
    assert "- deadline: Friday" in system


@pytest.mark.parametrize("memory_type", sorted(MEMORY))
def test_one_memory_type_alone(memory_type: str) -> None:
    system = _system(_render("agent_supervisor_router", **{memory_type: MEMORY[memory_type]}))
    assert "## Memory" in system
    assert system.count("### ") == 1


@pytest.mark.parametrize("name", NAMES)
def test_system_prompt_overrides_the_role_sentence(name: str) -> None:
    default = _system(_render(name))
    custom = _system(_render(name, system_prompt="You are the boss."))
    assert custom.startswith("You are the boss.")
    assert default.splitlines()[0] not in custom


# -- agent_supervisor_router -------------------------------------------------------------------------


def test_router_workers_progress_and_json_shape() -> None:
    messages = _render("agent_supervisor_router", workers=WORKERS, progress=PROGRESS)
    system, user = messages[0].content, messages[-1].content
    assert "- **researcher**: Finds sources on the web." in system
    assert "Skills: search, reading" in system
    assert "- **writer**: Writes clear prose." in system
    assert '{"next": "<worker name or FINISH>", "reason": ' in system
    assert '"instructions": ' in system
    assert "FINISH" in system
    assert "Write a market report on solar panels." in user
    assert "- researcher: Collected ten sources." in user


def test_router_without_progress_or_workers() -> None:
    messages = _render("agent_supervisor_router")
    assert "no workers were listed" in messages[0].content
    assert "No step has been taken yet." in messages[-1].content


# -- agent_supervisor_planner ------------------------------------------------------------------------


def test_planner_json_shape_and_limits() -> None:
    messages = _render("agent_supervisor_planner", workers=WORKERS, progress=PROGRESS, max_subtasks=4)
    system = messages[0].content
    assert '"subtasks": [{"id": "s1"' in system
    assert '"worker": "<worker name>"' in system
    assert '"depends_on": []' in system
    assert "at most 4 subtasks" in system
    assert "- researcher: Collected ten sources." in messages[-1].content


def test_planner_without_limit() -> None:
    assert "at most" not in _render("agent_supervisor_planner")[0].content


# -- agent_supervisor_reviewer -----------------------------------------------------------------------


def test_reviewer_criteria_and_json_shape() -> None:
    messages = _render(
        "agent_supervisor_reviewer",
        acceptance_criteria=["Cites at least three sources", "Under 500 words"],
        instructions="Draft the report.",
    )
    system, user = messages[0].content, messages[-1].content
    assert "- Cites at least three sources" in system
    assert "- Under 500 words" in system
    assert '{"decision": "approve" or "revise", "feedback": ' in system
    assert '"unmet_criteria": ' in system
    assert "## What writer was asked to do" in user
    assert "Draft the report." in user
    assert "## Result from writer" in user
    assert "Solar is growing." in user


def test_reviewer_default_criterion() -> None:
    system = _render("agent_supervisor_reviewer")[0].content
    assert "The result is correct, complete" in system


# -- agent_supervisor_hierarchical -------------------------------------------------------------------


def test_hierarchical_teams_reports_and_json_shapes() -> None:
    teams = [
        {
            "name": "research",
            "lead": "ada",
            "members": ["bo", "cy"],
            "purpose": "Studies the market.",
        },
        {"name": "design", "lead": "dee", "purpose": "Designs the product."},
    ]
    reports = [{"team": "research", "report": "The market is large."}]
    messages = _render(
        "agent_supervisor_hierarchical", teams=teams, team_reports=reports, progress=PROGRESS
    )
    system, user = messages[0].content, messages[-1].content
    assert "- **research** (lead: ada): Studies the market." in system
    assert "Members: bo, cy" in system
    assert "- **design** (lead: dee): Designs the product." in system
    assert '{"action": "delegate", "team": "<team name>"' in system
    assert '{"action": "final", ' in system
    assert "### research" in user
    assert "The market is large." in user
    assert "- researcher: Collected ten sources." in user


def test_hierarchical_without_reports() -> None:
    assert "No team has reported yet." in _render("agent_supervisor_hierarchical")[-1].content
