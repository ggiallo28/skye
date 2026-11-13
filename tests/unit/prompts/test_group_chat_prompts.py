"""Tests for the bundled group chat prompts and a scripted group chat."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from skye.base.dsl import PromptSpec, build
from skye.base.messages import AssistantMessage, SkyeMessage, SystemMessage, UserMessage
from skye.prompts.skye_prompts import load_prompt, render_prompt
from tests.unit.prompts.bundled import build_template, load_template, template_path


NAMES = ("agent_groupchat_participant", "agent_groupchat_manager", "agent_groupchat_summarizer")

TRANSCRIPT = [
    {"speaker": "user", "content": "We need a launch plan for Monday."},
    {"speaker": "planner", "content": "@finance can you check the budget?"},
]

REQUIRED: dict[str, dict[str, Any]] = {
    "agent_groupchat_participant": {"agent_name": "finance", "goal": "Agree on a launch plan."},
    "agent_groupchat_manager": {"goal": "Agree on a launch plan."},
    "agent_groupchat_summarizer": {"transcript": TRANSCRIPT},
}

PARTICIPANTS = [
    {"name": "planner", "role": "Breaks the work into steps.", "triggers": ["plan", "schedule"]},
    {"name": "finance", "role": "Owns the budget.", "triggers": ["budget", "cost"]},
    {"name": "legal", "triggers": ["contract"]},
]

TOOLS = [
    {
        "name": "calculator",
        "description": "Does arithmetic.",
        "parameters": {"expr": "string"},
        "returns": "a number",
    }
]

MEMORY: dict[str, list[dict[str, Any]]] = {
    "episodic_memory": [{"content": "Last launch slipped by a week.", "timestamp": "2026-10-01"}],
    "semantic_memory": [{"content": "The budget cap is 10k.", "source": "finance wiki"}],
    "procedural_memory": [{"name": "approval", "steps": ["draft", "sign off"]}],
    "persona_memory": [{"content": "Speaks plainly."}],
    "working_memory": [{"content": "Monday is a holiday in two regions."}],
}


def _spec(name: str) -> PromptSpec:
    return load_template(template_path(name), name)


def _render(
    name: str, history: list[SkyeMessage] | None = None, **variables: Any
) -> list[SkyeMessage]:
    return render_prompt(
        _spec(name), {**REQUIRED[name], **variables}, history={"history": history or []}
    )


# -- common to every group chat prompt ---------------------------------------------------------


@pytest.mark.parametrize("name", NAMES)
def test_has_front_matter(name: str) -> None:
    metadata = build_template(template_path(name)).metadata
    assert metadata["title"] and metadata["description"]
    assert metadata["version"] == "1.0"
    assert isinstance(metadata["tags"], list) and metadata["tags"]


@pytest.mark.parametrize("name", NAMES)
def test_roles_and_history(name: str) -> None:
    plain = _render(name)
    assert [type(m) for m in plain] == [SystemMessage, UserMessage]
    history: list[SkyeMessage] = [UserMessage(content="before"), AssistantMessage(content="after")]
    with_history = _render(name, history=history)
    assert [m.role for m in with_history] == ["system", "user", "assistant", "user"]
    assert with_history[1].content == "before"


@pytest.mark.parametrize("name", NAMES)
def test_missing_required_variable_raises(name: str) -> None:
    with pytest.raises(ValueError) as info:
        render_prompt(_spec(name), {})
    for variable in REQUIRED[name]:
        assert variable in str(info.value)


@pytest.mark.parametrize("name", NAMES)
def test_tools_and_memory_sections(name: str) -> None:
    bare = _render(name)[0].content
    assert "## Tools" not in bare
    assert "## Memory" not in bare
    system = _render(name, tools=TOOLS, **MEMORY)[0].content
    assert "## Tools" in system
    assert "- **calculator**: Does arithmetic." in system
    assert 'Parameters: {"expr": "string"}' in system
    assert "Returns: a number" in system
    assert "## Memory" in system
    for heading in (
        "### Past events",
        "### Known facts",
        "### Procedures",
        "### Persona",
        "### Current notes",
    ):
        assert heading in system
    assert "- [2026-10-01] Last launch slipped by a week." in system
    assert "- The budget cap is 10k. (source: finance wiki)" in system
    assert "  * sign off" in system
    assert "- Monday is a holiday in two regions." in system


@pytest.mark.parametrize("name", NAMES)
def test_system_prompt_override(name: str) -> None:
    system = _render(name, system_prompt="Custom role.")[0].content
    assert system.startswith("Custom role.")


@pytest.mark.parametrize("name", NAMES)
def test_transcript_is_rendered_speaker_colon_content(name: str) -> None:
    user = _render(name, transcript=TRANSCRIPT)[-1].content
    assert "user: We need a launch plan for Monday." in user
    assert "planner: @finance can you check the budget?" in user


# -- agent_groupchat_participant --------------------------------------------------------------------


def test_participant_triggers_mentions_and_tokens() -> None:
    system = _render(
        "agent_groupchat_participant",
        agent_role="Owns the budget.",
        participants=PARTICIPANTS,
        triggers=["budget", "cost"],
    )[0].content
    assert "You are finance" in system
    assert "Your role: Owns the budget." in system
    assert "Agree on a launch plan." in system
    assert "- @planner: Breaks the work into steps." in system
    assert "- @legal" in system
    assert "mentions you as @finance" in system
    assert "  * budget" in system
    assert "  * cost" in system
    assert "reply with exactly [PASS] and nothing else" in system
    assert "end your reply with [DONE]" in system
    assert "@name" in system


def test_participant_without_mentions_or_triggers() -> None:
    system = _render("agent_groupchat_participant", respond_when_mentioned=False)[0].content
    assert "mentions you" not in system
    assert "falls within your role" in system


def test_participant_custom_tokens() -> None:
    messages = _render("agent_groupchat_participant", pass_token="<skip>", end_token="<end>")
    assert "exactly <skip>" in messages[0].content
    assert "with <end>" in messages[0].content
    assert "<skip>" in messages[-1].content


def test_participant_empty_transcript() -> None:
    assert "(nobody has spoken yet)" in _render("agent_groupchat_participant")[-1].content


# -- agent_groupchat_manager ------------------------------------------------------------------------


def test_manager_participants_triggers_and_json_shapes() -> None:
    messages = _render(
        "agent_groupchat_manager",
        participants=PARTICIPANTS,
        transcript=TRANSCRIPT,
        last_message="planner: @finance can you check the budget?",
        max_speakers=2,
    )
    system, user = messages[0].content, messages[-1].content
    assert "- @finance: Owns the budget." in system
    assert "Speaks on: budget, cost" in system
    assert "Speaks on: contract" in system
    assert "choose at most 2" in system
    assert '{"next_speakers": ["<name>"], "reason": ' in system
    assert '{"next_speakers": [], "end": true, ' in system
    assert "## Last message" in user
    assert "planner: @finance can you check the budget?" in user


def test_manager_defaults() -> None:
    messages = _render("agent_groupchat_manager")
    assert "choose at most 1" in messages[0].content
    assert "[DONE]" in messages[0].content
    assert "last line of the conversation above" in messages[-1].content


# -- agent_groupchat_summarizer ---------------------------------------------------------------------


def test_summarizer_markdown_sections() -> None:
    messages = _render(
        "agent_groupchat_summarizer", goal="Agree on a launch plan.", participants=PARTICIPANTS
    )
    system = messages[0].content
    for heading in ("### Summary", "### Decisions", "### Open questions", "### Action items"):
        assert heading in system
    assert "- finance: Owns the budget." in system
    assert "Agree on a launch plan." in system


def test_summarizer_json_and_options() -> None:
    messages = _render(
        "agent_groupchat_summarizer",
        output_format="json",
        focus_agent="legal",
        max_words=120,
        previous_summary="Launch was proposed for Monday.",
    )
    system, user = messages[0].content, messages[-1].content
    assert '"decisions": ' in system
    assert '"open_questions": ' in system
    assert '"action_items": {"<participant>": ["<task>"]}' in system
    assert "### Summary" not in system
    assert "Write for legal" in system
    assert "at most 120 words" in system
    assert "## Summary so far" in user
    assert "Launch was proposed for Monday." in user


# -- a scripted group chat ---------------------------------------------------------------------

PASS = "[PASS]"


class ScriptedModel:
    """A fake model: speaks when its trigger word or @name is in another agent's last message."""

    def __init__(self, triggers: dict[str, list[str]]) -> None:
        self.triggers = triggers
        self.calls: list[list[SkyeMessage]] = []

    def __call__(self, messages: list[SkyeMessage]) -> str:
        self.calls.append(messages)
        system, user = messages[0].content, messages[-1].content
        name = re.search(r"^You are (\w+),", system, re.M).group(1)  # type: ignore[union-attr]
        pass_token = re.search(r"reply with exactly (\S+) and nothing else", system).group(1)  # type: ignore[union-attr]
        lines = user.split("\n")
        speaker, content = (
            lines[lines.index("## Conversation so far") + 1 : -1][-1].lower().split(": ", 1)
        )
        if speaker != name and (
            f"@{name}" in content or any(word in content for word in self.triggers[name])
        ):
            return f"{name} here, about: {content}"
        return pass_token


def _round(model: ScriptedModel, transcript: list[dict[str, str]]) -> list[str]:
    """One round: every agent reads the shared transcript; the ones that do not pass speak."""
    spoke = []
    for name, words in model.triggers.items():
        messages = _render(
            "agent_groupchat_participant",
            agent_name=name,
            participants=[{"name": n} for n in model.triggers],
            triggers=words,
            transcript=transcript,
        )
        reply = model(messages)
        if reply != PASS:
            spoke.append(name)
    return spoke


def test_simulation_only_triggered_agents_speak() -> None:
    model = ScriptedModel(
        {"planner": ["plan", "schedule"], "finance": ["budget", "cost"], "legal": ["contract"]}
    )

    transcript = [{"speaker": "user", "content": "What will the launch cost?"}]
    assert _round(model, transcript) == ["finance"]

    transcript.append(
        {"speaker": "user", "content": "Please review the contract and the schedule."}
    )
    assert _round(model, transcript) == ["planner", "legal"]

    transcript.append({"speaker": "user", "content": "Thanks everyone, see you tomorrow."})
    assert _round(model, transcript) == []

    transcript.append({"speaker": "planner", "content": "@legal one more question."})
    assert _round(model, transcript) == ["legal"]

    assert len(model.calls) == 12


def test_manager_output_shape_parses_from_scripted_reply() -> None:
    """The manager's documented shapes are valid JSON a caller can act on."""
    system = _render("agent_groupchat_manager", participants=PARTICIPANTS)[0].content
    shapes = [
        json.loads(line) for line in system.splitlines() if line.startswith('{"next_speakers"')
    ]
    assert shapes[0]["next_speakers"] == ["<name>"]
    assert shapes[1] == {
        "next_speakers": [],
        "end": True,
        "reason": "<why the conversation is over>",
    }
