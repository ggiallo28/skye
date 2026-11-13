"""Tests for the bundled ``agent_planner.skye`` prompt (plan, execute and replan phases)."""

from __future__ import annotations

from typing import Any

import pytest

from skye.base.dsl import PromptSpec, build
from skye.base.messages import SkyeMessage
from skye.prompts.skye_prompts import load_prompt, render_prompt
from tests.unit.prompts.bundled import GALLERY_DIR, build_template, gallery_builder, load_template

TEMPLATE = GALLERY_DIR / "agent_planner.skye"

TOOLS = [
    {
        "name": "web_search",
        "description": "Search the web",
        "parameters": {"query": "string"},
        "returns": "a list of links",
    },
    {"name": "calculator", "description": "Evaluate arithmetic"},
]

MEMORIES: dict[str, list[dict[str, Any]]] = {
    "episodic_memory": [
        {"content": "User asked for a trip budget", "timestamp": "2026-11-01"},
        {"content": "User prefers trains"},
    ],
    "semantic_memory": [
        {"content": "Rome is in Italy", "source": "atlas"},
        {"content": "A week has 7 days"},
    ],
    "procedural_memory": [
        {"name": "trip_budget", "steps": ["list costs", "sum costs"]},
        {"name": "short_answer", "content": "Answer in one line"},
    ],
    "persona_memory": [{"content": "The user is a student", "source": "profile"}],
    "working_memory": [{"name": "budget", "content": "500 EUR"}, {"content": "draft started"}],
}

PLAN = [
    {
        "id": 1,
        "description": "Find train prices",
        "tool": "web_search",
        "depends_on": [],
        "done_when": "a price is found",
    },
    {
        "id": 2,
        "description": "Add up the costs",
        "tool": "calculator",
        "depends_on": [1],
        "done_when": "a total is computed",
    },
]


@pytest.fixture(scope="module")
def spec() -> PromptSpec:
    return load_template(TEMPLATE, "agent_planner")


def _render(spec: PromptSpec, **variables: Any) -> list[SkyeMessage]:
    return list(render_prompt(spec, {"task": "Plan a trip to Rome", **variables}))


def _system(messages: list[SkyeMessage]) -> str:
    return str(messages[0].content)


def _user(messages: list[SkyeMessage]) -> str:
    return str(messages[-1].content)


def test_has_front_matter() -> None:
    metadata = build_template(TEMPLATE).metadata
    assert metadata["title"] and metadata["description"]
    assert metadata["version"] == "1.0"
    assert isinstance(metadata["tags"], list) and metadata["tags"]


def test_loads_with_expected_name(spec: PromptSpec) -> None:
    assert spec.name == "agent_planner"


def test_task_is_required(spec: PromptSpec) -> None:
    with pytest.raises(ValueError, match="task"):
        render_prompt(spec, {})


def test_plan_is_default_phase_with_json_shape(spec: PromptSpec) -> None:
    messages = _render(spec)
    assert [m.role for m in messages] == ["system", "user"]
    system = _system(messages)
    assert "You are a planning agent" in system
    assert "make a plan" in system
    assert '{"goal": ' in system and '"steps": [{"id": 1' in system
    for key in ('"description"', '"tool"', '"depends_on"', '"done_when"'):
        assert key in system
    assert "at most 7 steps" in system
    assert "final_answer" not in system
    assert "Plan a trip to Rome" in _user(messages)
    assert "Write the plan." in _user(messages)


def test_plan_without_tools_or_memory(spec: PromptSpec) -> None:
    system = _system(_render(spec))
    assert "## Tools" not in system
    assert "No tools are available" in system
    assert "## Memory" not in system
    assert "## Constraints" not in system


def test_plan_with_tools(spec: PromptSpec) -> None:
    system = _system(_render(spec, tools=TOOLS))
    assert "## Tools" in system
    assert "- **web_search**: Search the web" in system
    assert 'Parameters: {"query": "string"}' in system
    assert "Returns: a list of links" in system
    assert "- **calculator**: Evaluate arithmetic" in system
    assert "No tools are available" not in system


def test_every_memory_type(spec: PromptSpec) -> None:
    system = _system(_render(spec, **MEMORIES))
    assert "## Memory" in system
    assert "### Persona" in system and "- The user is a student (source: profile)" in system
    assert "### Past events" in system
    assert "- [2026-11-01] User asked for a trip budget" in system
    assert "- User prefers trains" in system
    assert "### Known facts" in system and "- Rome is in Italy (source: atlas)" in system
    assert "- A week has 7 days" in system
    assert "### Procedures" in system and "- trip_budget" in system
    assert "  * list costs" in system and "  Answer in one line" in system
    assert "### Current notes" in system and "- budget: 500 EUR" in system
    assert "- draft started" in system
    assert "reuse its steps" in system


@pytest.mark.parametrize("kind", sorted(MEMORIES))
def test_single_memory_type_alone(spec: PromptSpec, kind: str) -> None:
    system = _system(_render(spec, **{kind: MEMORIES[kind]}))
    assert "## Memory" in system
    headings = {
        "### Persona",
        "### Past events",
        "### Known facts",
        "### Procedures",
        "### Current notes",
    }
    assert sum(h in system for h in headings) == 1


def test_procedure_reuse_hint_only_with_procedural_memory(spec: PromptSpec) -> None:
    system = _system(_render(spec, semantic_memory=MEMORIES["semantic_memory"]))
    assert "reuse its steps" not in system


def test_options_and_system_prompt(spec: PromptSpec) -> None:
    system = _system(
        _render(
            spec,
            max_steps=3,
            constraints=["Stay under budget"],
            system_prompt="You plan trips.",
        )
    )
    assert system.startswith("You plan trips.")
    assert "You are a planning agent" not in system
    assert "## Constraints" in system and "- Stay under budget" in system
    assert "at most 3 steps" in system


def test_history_placeholder(spec: PromptSpec) -> None:
    history = [{"role": "user", "content": "earlier"}, {"role": "assistant", "content": "reply"}]
    messages = list(
        render_prompt(spec, {"task": "Plan a trip to Rome"}, history={"history": history})
    )
    assert [m.role for m in messages] == ["system", "user", "assistant", "user"]
    assert messages[1].content == "earlier"
    assert "Plan a trip to Rome" in _user(messages)


def test_execute_phase(spec: PromptSpec) -> None:
    messages = _render(
        spec,
        phase="execute",
        plan=PLAN,
        current_step=PLAN[1],
        completed_steps=[{"id": 1, "result": "120 EUR"}],
        tools=TOOLS,
    )
    assert [m.role for m in messages] == ["system", "user"]
    system, user = _system(messages), _user(messages)
    assert "execute one step" in system
    assert "make a plan" not in system and "revise the plan" not in system
    assert "## Plan" in user and "1. Find train prices" in user
    assert "Tool: web_search" in user and "Depends on: 1" in user
    assert "## Finished steps" in user and "- Step 1: 120 EUR" in user
    assert "## Current step" in user and "2. Add up the costs" in user
    assert "Done when: a total is computed" in user
    assert "Carry out this step." in user


def test_execute_without_tools_or_progress(spec: PromptSpec) -> None:
    user = _user(_render(spec, phase="execute", plan=PLAN, current_step=PLAN[0]))
    assert "No step has been finished yet." in user
    assert "1. Find train prices" in user


def test_replan_phase(spec: PromptSpec) -> None:
    messages = _render(
        spec,
        phase="replan",
        plan=PLAN,
        completed_steps=[{"id": 1, "result": "no prices found"}],
        observation="The site was down",
        error="HTTP 503",
    )
    system, user = _system(messages), _user(messages)
    assert "revise the plan" in system
    assert '{"goal": ' in system and '"steps": [' in system
    assert '{"final_answer": ' in system
    assert "## Observation" in user and "The site was down" in user
    assert "## Error" in user and "HTTP 503" in user
    assert "- Step 1: no prices found" in user
    assert "Revise the remaining plan" in user


def test_replan_without_observation_or_error(spec: PromptSpec) -> None:
    user = _user(_render(spec, phase="replan", plan=PLAN))
    assert "## Observation" not in user and "## Error" not in user


def test_renders_via_builder() -> None:
    messages = gallery_builder().render(
        "agent_planner",
        {
            "task": "Plan a trip to Rome",
            "phase": "replan",
            "plan": PLAN,
            "completed_steps": [{"id": 1, "result": "120 EUR"}],
            "tools": TOOLS,
            **MEMORIES,
        },
    )
    assert [m.role for m in messages] == ["system", "user"]
    assert "final_answer" in str(messages[0].content)
    assert "Plan a trip to Rome" in str(messages[-1].content)
