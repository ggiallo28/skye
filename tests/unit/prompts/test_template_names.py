"""The names of the bundled templates and of the gallery follow one convention (task 24.10, D118).

A name is ``scope_detail[_detail]``: the scope is one of ``agent``, ``chat``, ``text``, ``extraction`` or
``generation``, in lower case with underscores. Every agent starts with ``agent_`` (a memory agent is
``agent_memory_<x>``); a prompt that is not an agent takes the scope of its task.
"""

from __future__ import annotations

import re

from skye.prompts import loaders
from tests.unit.prompts.bundled import GALLERY_DIR

PATTERN = re.compile(r"^(agent|chat|text|extraction|generation)(_[a-z]+)+$")

#: The agents of the catalogue: a template whose name starts with ``agent_`` is one of these.
AGENTS = (
    "agent_code",
    "agent_form",
    "agent_groupchat_manager",
    "agent_groupchat_participant",
    "agent_groupchat_summarizer",
    "agent_memory_assistant",
    "agent_memory_consolidation",
    "agent_memory_recall",
    "agent_memory_update",
    "agent_memory_working",
    "agent_multimodal",
    "agent_planner",
    "agent_procedure",
    "agent_reasoning",
    "agent_reasoning_chain_of_thought",
    "agent_reasoning_self_reflection",
    "agent_reasoning_tree_of_thoughts",
    "agent_smol_code",
    "agent_smol_managed",
    "agent_smol_planning",
    "agent_react",
    "agent_supervisor_hierarchical",
    "agent_supervisor_planner",
    "agent_supervisor_reviewer",
    "agent_supervisor_router",
    "agent_tool",
)


def _gallery() -> list[str]:
    return sorted(path.stem for path in GALLERY_DIR.glob("*.skye"))


def _all() -> list[str]:
    return sorted([*loaders.bundled_names(), *_gallery()])


def test_every_template_name_follows_the_convention():
    bad = [n for n in _all() if not PATTERN.match(n)]
    assert not bad, f"names that break scope_detail with a known scope: {bad}"


def test_the_agents_are_exactly_the_templates_that_start_with_agent():
    agents = sorted(n for n in _all() if n.startswith("agent_"))
    assert agents == sorted(AGENTS)


def test_the_name_of_the_prompt_inside_the_file_is_the_name_of_the_file():
    for name in loaders.bundled_names():
        assert f'prompt "{name}"' in loaders.read_bundled(name), name
    for name in _gallery():
        text = (GALLERY_DIR / f"{name}.skye").read_text(encoding="utf-8")
        assert f'prompt "{name}"' in text, name
