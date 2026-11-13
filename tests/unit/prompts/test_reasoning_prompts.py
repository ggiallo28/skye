"""Tests for the bundled reasoning prompts (self reflection, chain of thought, tree of thoughts)."""

from __future__ import annotations

from typing import Any

import pytest

from skye.base.dsl import PromptSpec, build
from skye.base.messages import AssistantMessage, SkyeMessage, SystemMessage, UserMessage
from skye.prompts.skye_prompts import load_prompt, render_prompt
from tests.unit.prompts.bundled import build_template, load_template, template_path

NAMES = ["agent_reasoning_self_reflection", "agent_reasoning_chain_of_thought", "agent_reasoning_tree_of_thoughts"]

TOOLS = [
    {
        "name": "calculator",
        "description": "Evaluates an arithmetic expression.",
        "parameters": {"expression": "the expression to evaluate"},
        "returns": "the numeric result",
    },
    {"name": "lookup", "description": "Looks up a fact."},
]

MEMORIES: dict[str, list[dict[str, Any]]] = {
    "persona_memory": [{"content": "The user prefers short answers.", "source": "profile"}],
    "episodic_memory": [{"content": "The user asked about primes.", "timestamp": "2026-11-01"}],
    "semantic_memory": [
        {"content": "2 is the only even prime.", "source": "textbook"},
        {"content": "1 is not prime."},
    ],
    "procedural_memory": [
        {
            "name": "check primality",
            "steps": ["try divisors up to the square root", "stop at the first divisor"],
        },
        {"content": "Always double-check arithmetic."},
    ],
    "working_memory": [
        {"name": "goal", "content": "list primes under 20"},
        {"content": "scratch note"},
    ],
}

MEMORY_HEADINGS = {
    "persona_memory": "### Persona",
    "episodic_memory": "### Past events",
    "semantic_memory": "### Known facts",
    "procedural_memory": "### Procedures",
    "working_memory": "### Current notes",
}

PHASES = {
    "agent_reasoning_self_reflection": ["act", "reflect", "revise"],
    "agent_reasoning_chain_of_thought": [None],
    "agent_reasoning_tree_of_thoughts": ["propose", "evaluate", "solve"],
}

HISTORY = [UserMessage(content="earlier question"), AssistantMessage(content="earlier answer")]


@pytest.fixture(scope="module", params=NAMES)
def spec(request: pytest.FixtureRequest) -> PromptSpec:
    name = request.param
    return load_template(template_path(name), name)


def _load(name: str) -> PromptSpec:
    return load_template(template_path(name), name)


def _render(
    name: str, history: list[SkyeMessage] | None = None, **variables: Any
) -> list[SkyeMessage]:
    variables.setdefault("task", "Find the primes under 20.")
    return render_prompt(_load(name), variables, history={"history": history or []})


def _system(messages: list[SkyeMessage]) -> str:
    assert isinstance(messages[0], SystemMessage)
    return messages[0].content


def _all_phase_cases() -> list[tuple[str, str | None]]:
    return [(name, phase) for name in NAMES for phase in PHASES[name]]


def _phase_vars(phase: str | None) -> dict[str, Any]:
    return {} if phase is None else {"phase": phase}


# -- shape ---------------------------------------------------------------------------------------


def test_each_file_has_front_matter() -> None:
    for name in NAMES:
        metadata = build_template(template_path(name)).metadata
        assert metadata["title"] and metadata["description"]
        assert metadata["version"] == "1.0"
        assert isinstance(metadata["tags"], list) and metadata["tags"]


def test_shared_variables_declared(spec: PromptSpec) -> None:
    names = {v.name for v in spec.variables}
    shared = {"system_prompt", "task", "tools", *MEMORIES}
    assert shared <= names
    task = next(v for v in spec.variables if v.name == "task")
    assert task.required


def test_missing_task_raises(spec: PromptSpec) -> None:
    with pytest.raises(ValueError, match="task"):
        render_prompt(spec, {})


@pytest.mark.parametrize(("name", "phase"), _all_phase_cases())
def test_minimal_render_roles(name: str, phase: str | None) -> None:
    messages = _render(name, **_phase_vars(phase))
    assert isinstance(messages[0], SystemMessage)
    assert isinstance(messages[-1], UserMessage)
    assert "Find the primes under 20." in messages[-1].content
    system = _system(messages)
    assert "## Tools" not in system
    assert "## Memory" not in system
    assert "{{" not in system and "{{" not in messages[-1].content


@pytest.mark.parametrize(("name", "phase"), _all_phase_cases())
def test_tools_section(name: str, phase: str | None) -> None:
    system = _system(_render(name, tools=TOOLS, **_phase_vars(phase)))
    assert "## Tools" in system
    assert "- **calculator**: Evaluates an arithmetic expression." in system
    assert 'Parameters: {"expression": "the expression to evaluate"}' in system
    assert "Returns: the numeric result" in system
    assert "- **lookup**: Looks up a fact." in system


@pytest.mark.parametrize(("name", "phase"), _all_phase_cases())
@pytest.mark.parametrize("memory", list(MEMORIES))
def test_each_memory_type_alone(name: str, phase: str | None, memory: str) -> None:
    system = _system(_render(name, **{memory: MEMORIES[memory]}, **_phase_vars(phase)))
    assert "## Memory" in system
    assert MEMORY_HEADINGS[memory] in system
    for other, heading in MEMORY_HEADINGS.items():
        if other != memory:
            assert heading not in system


def test_memory_items_rendered() -> None:
    system = _system(_render("agent_reasoning_chain_of_thought", **MEMORIES))
    assert "- The user prefers short answers. (source: profile)" in system
    assert "- [2026-11-01] The user asked about primes." in system
    assert "- 2 is the only even prime. (source: textbook)" in system
    assert "- 1 is not prime." in system
    assert "- check primality" in system
    assert "  * try divisors up to the square root" in system
    assert "  Always double-check arithmetic." in system
    assert "- goal: list primes under 20" in system
    assert "- scratch note" in system


@pytest.mark.parametrize("name", NAMES)
def test_system_prompt_overrides_role(name: str) -> None:
    default = _system(_render(name))
    custom = _system(_render(name, system_prompt="You are Marvin."))
    assert custom.startswith("You are Marvin.")
    assert default.splitlines()[0] not in custom


@pytest.mark.parametrize("name", NAMES)
def test_history_placeholder(name: str) -> None:
    messages = _render(name, history=HISTORY)
    roles = [m.role for m in messages]
    assert roles[-3:] == ["user", "assistant", "user"]
    assert messages[-3].content == "earlier question"
    assert messages[-2].content == "earlier answer"


# -- agent_reasoning_self_reflection ----------------------------------------------------------------------


def test_reflection_act_is_default() -> None:
    messages = _render("agent_reasoning_self_reflection", previous_attempt="old", feedback="bad")
    assert "## Current phase: act" in _system(messages)
    assert "## Previous attempt" not in messages[-1].content
    assert "## Feedback" not in messages[-1].content
    assert messages[-1].content.endswith("Answer the task.")


def test_reflection_reflect() -> None:
    messages = _render(
        "agent_reasoning_self_reflection",
        phase="reflect",
        previous_attempt="2, 3, 5, 7, 9",
        feedback="9 is not prime",
        test_results=["test_primes: failed"],
        reflections=["check odd numbers"],
    )
    system, user = _system(messages), messages[-1].content
    assert "## Current phase: reflect" in system
    assert "Diagnosis:" in system and "Lessons:" in system
    assert "## Previous attempt\n2, 3, 5, 7, 9" in user
    assert "## Feedback on the previous attempt\n9 is not prime" in user
    assert "## Test results\n- test_primes: failed" in user
    assert "## Earlier lessons\n- check odd numbers" in user


def test_reflection_reflect_without_feedback() -> None:
    user = _render("agent_reasoning_self_reflection", phase="reflect", previous_attempt="x")[-1].content
    assert "## Feedback" not in user
    assert "## Test results" not in user
    assert "lessons" not in user.lower()


def test_reflection_revise() -> None:
    messages = _render(
        "agent_reasoning_self_reflection",
        phase="revise",
        previous_attempt="2, 3, 5, 7, 9",
        reflections=["9 = 3 * 3"],
    )
    system, user = _system(messages), messages[-1].content
    assert "## Current phase: revise" in system
    assert "## Previous attempt" in user
    assert "## Lessons from earlier attempts\n- 9 = 3 * 3" in user
    assert user.endswith("Write the improved answer.")


def test_reflection_act_with_reflections() -> None:
    user = _render("agent_reasoning_self_reflection", reflections=["show your work"])[-1].content
    assert "## Lessons from earlier attempts\n- show your work" in user


# -- agent_reasoning_chain_of_thought ---------------------------------------------------------------------

EXAMPLE = {"question": "Is 9 prime?", "reasoning": "Step 1: 9 = 3 * 3.", "answer": "No"}


def test_cot_shows_reasoning_by_default() -> None:
    system = _system(_render("agent_reasoning_chain_of_thought"))
    assert "Step 1:" in system
    assert "Final answer:" in system


def test_cot_hidden_reasoning() -> None:
    system = _system(_render("agent_reasoning_chain_of_thought", show_reasoning=False))
    assert "Step 1:" not in system
    assert "do not write the steps" in system


def test_cot_examples_become_turns() -> None:
    messages = _render("agent_reasoning_chain_of_thought", examples=[EXAMPLE], history=HISTORY)
    roles = [m.role for m in messages]
    assert roles == ["system", "user", "assistant", "user", "assistant", "user"]
    assert messages[1].content == "Is 9 prime?"
    assert messages[2].content == "Step 1: 9 = 3 * 3.\nFinal answer: No"


def test_cot_examples_without_reasoning() -> None:
    messages = _render("agent_reasoning_chain_of_thought", examples=[EXAMPLE], show_reasoning=False)
    assert messages[2].content == "Final answer: No"


# -- agent_reasoning_tree_of_thoughts ---------------------------------------------------------------------


def test_tot_propose_default() -> None:
    messages = _render("agent_reasoning_tree_of_thoughts")
    system, user = _system(messages), messages[-1].content
    assert "## Current phase: propose" in system
    assert "Suggest 3 different candidates" in system
    assert "Thought <n>:" in system
    assert "The path is empty" in user
    assert user.endswith("Propose exactly 3 candidate next thoughts.")


def test_tot_propose_breadth_and_path() -> None:
    user = _render("agent_reasoning_tree_of_thoughts", breadth=5, path=["start from 2"])[-1].content
    assert "## Current path\n- start from 2" in user
    assert "exactly 5 candidate" in user


def test_tot_evaluate_labels() -> None:
    messages = _render(
        "agent_reasoning_tree_of_thoughts", phase="evaluate", candidates=["try 4", "try 9"], path=["p"]
    )
    system, user = _system(messages), messages[-1].content
    assert "## Current phase: evaluate" in system
    assert "Candidate <n>: <sure|likely|impossible> - <one-line justification>" in system
    assert "## Candidates\n- try 4\n- try 9" in user


def test_tot_evaluate_numeric() -> None:
    system = _system(
        _render("agent_reasoning_tree_of_thoughts", phase="evaluate", candidates=["a"], scoring="number")
    )
    assert "Candidate <n>: <score from 1 to 10> - <one-line justification>" in system
    assert "sure|likely|impossible" not in system


def test_tot_evaluate_no_candidates() -> None:
    user = _render("agent_reasoning_tree_of_thoughts", phase="evaluate")[-1].content
    assert "(no candidates were given)" in user


def test_tot_solve() -> None:
    messages = _render("agent_reasoning_tree_of_thoughts", phase="solve", path=["a", "b"])
    system, user = _system(messages), messages[-1].content
    assert "## Current phase: solve" in system
    assert "Final answer:" in system
    assert "## Current path\n- a\n- b" in user
    assert "## Candidates" not in user
    no_path = _render("agent_reasoning_tree_of_thoughts", phase="solve")[-1].content
    assert "No path was selected" in no_path
