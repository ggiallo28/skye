"""Equivalence of the bundled `.jinja` prompts and their `.skye` conversions (task 4.4, D60).

For every converted ``src/skye/prompts/templates/<name>.skye``, this test compares the new
``.skye`` prompt with the frozen output of the old ``.jinja`` template for the same data. The old
templates used ``{% if %}`` and ``{% for %}``, which the engine no longer runs (decision D76, task
9.1), so their output was rendered once, before the tags were removed, and frozen in
``tests/unit/prompts/legacy_renderings/<name>.json``: one rendered text per case of
``equivalence_cases/<name>.json``, in the same order.

How each side is rendered:
    * Legacy: the frozen text of the case, split into role sections at lines that are exactly
      ``[SYSTEM]``, ``[USER]`` or ``[ASSISTANT]`` (after stripping). Text before the first marker
      is a ``user`` section. Sections whose normalised text is empty are dropped. Each section is
      one ``(role, content)`` message.
    * New: ``skye.prompts.skye_prompts.load_prompt(skye_text, name=<name>)`` followed by
      ``render_prompt(spec, variables, history=<case history>)``. The prompt inside
      ``<name>.skye`` must be named ``<name>`` (``prompt "<name>" { ... }``).

Normalisation (applied to the content of every message on both sides): strip each line, collapse
runs of spaces and tabs into one space, drop blank lines, join the remaining lines with ``"\\n"``.
Then the two lists of ``(role, content)`` pairs must be equal, message by message.

Case files (frozen with the conversion; a case cannot be added without its old output):
    ``tests/unit/prompts/equivalence_cases/<name>.json`` is a JSON list of cases. A ``.skye``
    template without a case file fails the test. Each case is either

    * a plain object of variables, e.g. ``{"user_message": "Hi", "domain": "law"}``; or
    * the wrapped form (preferred when you need a note or history), recognised by having a
      ``"variables"`` key whose value is an object; only the keys ``variables``, ``history``,
      ``note``, ``glued_lines`` and ``skye_variables`` are allowed::

          {
            "note": "history present, no context",
            "variables": {"user_message": "Hi"},
            "history": {"chat_history": [{"role": "user", "content": "Hello"}]},
            "glued_lines": false
          }

      ``note`` (optional) is shown in the failure message. ``history`` (optional) maps a name to
      a list of ``{"role", "content"}`` objects. On the legacy side the entries were merged into
      the variables (the old templates read history as a variable and print ``[ROLE]`` markers
      for it); on the new side they are passed as ``render_prompt(history=...)``, which a
      ``placeholder "<name>"`` consumes. A ``placeholder`` also falls back to a variable of the
      same name, so putting the history list in ``variables`` works too. ``glued_lines``
      (optional, default false) is for a case whose legacy output glues lines together (intended
      difference 5): both sides are then compared with all whitespace removed. Set it only on
      the cases that need it; every other case is compared line by line. ``skye_variables``
      (optional) are merged over ``variables`` for the .skye side only, for a template whose
      inputs changed shape (intended differences 6 and 7): e.g. the old ``chat_history`` list in
      ``variables`` and the same turns as ``history`` in ``skye_variables`` (read by the
      ``placeholder "history"``).

    The cases cover every ``if``/``elif``/``else`` and ``for`` branch of the old template (each
    branch taken and not taken, empty and non-empty lists).

Intended differences between the old and the new rendering are listed in
``INTENDED_DIFFERENCES`` below; everything else must match. Add an entry there when a conversion
needs a new, deliberate difference.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from skye.prompts.skye_prompts import load_prompt, render_prompt
from tests.unit.prompts.bundled import BUNDLED_DIR, GALLERY_DIR, load_template, template_path

INTENDED_DIFFERENCES: list[str] = [
    # 0. Task 24.6: the memories of agent_memory_assistant and agent_memory_recall are the standard section.
    "agent_memory_assistant and agent_memory_recall show their memories in the standard section '## Memory' of "
    "common/memories.skye (they had sections of their own); a case with memory items is not compared "
    "with the legacy text.",
    # 1. Real roles instead of text markers.
    "Roles are real message roles (SystemMessage, UserMessage, AssistantMessage) instead of the "
    "[SYSTEM]/[USER]/[ASSISTANT] text markers; the harness splits the legacy output at the "
    "markers so both sides are compared as (role, content) pairs.",
    # 2. Conversation history becomes real messages.
    "A conversation history printed by the old template as '[ROLE]' + content sections becomes "
    "real messages (via `placeholder` or `each ... { message turn.role { ... } }`); the marker "
    "split makes the legacy side comparable, so no special case is needed.",
    # 3. Whitespace.
    "Spaces and blank lines are not significant: lines are stripped, runs of spaces collapse, "
    "blank lines are dropped (the old whitespace control is not reproduced exactly).",
    # 4. Empty messages.
    "A message whose text is empty after rendering is omitted on both sides.",
    # 5. Lines glued by the old whitespace control.
    "Lines that the old templates glued together because an '{% endif %}' swallowed the newline "
    "(trim_blocks) are separate lines in .skye. Seen in agent_memory_assistant and agent_memory_recall (2+ "
    "memories: '- I like tea (2024-01-01)- I live in Rome'). A case that exercises "
    'such a shape sets "glued_lines": true; the harness then compares each message with its '
    "whitespace removed, so the text and its order must still match exactly."
    " Also seen in agent_form (field Type / Options / Validation lines) and agent_multimodal "
    "('URL:' and 'Transcript:' lines).",
    # 6. Inputs that changed shape (owner request, 2026-11-08).
    "classification takes one 'categories' list of {name, description?} instead of a list of "
    "names plus 'category_descriptions'; its cases give the old variables to the legacy side and "
    "the new list in 'skye_variables'.",
    # 7. Structured inputs and unified names (owner decision 2026-11-08, no backward compatibility).
    "Every list or map input has a structured type and the agent inputs use the unified names "
    "(chat_history / conversation_history -> placeholder 'history', declarative_memory -> "
    "semantic_memory, procedural_memories / procedures -> procedural_memory, personality -> a "
    "list of strings); a case gives the old variables to the legacy side and the new ones in "
    "'skye_variables'.",
    # 8. No heading before the conversation history.
    "The '## Recent conversation:' / '## Previous discussion:' / '## Previous conversation:' line "
    "the old agent templates printed before the history is gone (the history is a placeholder, "
    "real messages); the harness drops exactly that line from the legacy system message of the "
    "templates listed in LEGACY_HISTORY_HEADINGS.",
    # 9. Task 24.12: two templates are one.
    "generation_code and generation_sql are one template, generation_code, with generic variables (language, "
    "input, references, environment, constraints, examples, detailed, format); their legacy cases are no "
    "longer compared, and tests/unit/prompts/test_generation_merge.py pins the renderings of both old templates "
    "and lists every intended change.",
]

# Intended difference 8: the heading line each old template printed before its history.
LEGACY_HISTORY_HEADINGS: dict[str, str] = {
    "agent_code": "## Previous discussion:",
    "agent_form": "## Recent conversation:",
    "agent_memory_assistant": "## Recent conversation:",
    "agent_memory_recall": "## Recent conversation:",
    "agent_multimodal": "## Previous conversation:",
    "agent_procedure": "## Recent conversation:",
    "agent_reasoning": "## Previous discussion:",
    "agent_tool": "## Recent conversation:",
}

REPO_ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
LEGACY_DIR = HERE / "legacy_renderings"
CASES_DIR = HERE / "equivalence_cases"

_MARKER = re.compile(r"^\[(SYSTEM|USER|ASSISTANT)\]$")
_SPACES = re.compile(r"[ \t]+")

# Only conversions are compared: a new prompt written directly in .skye has no legacy template.
SKYE_NAMES = sorted(
    p.stem for p in [*BUNDLED_DIR.glob("*.skye"), *GALLERY_DIR.glob("*.skye")] if (LEGACY_DIR / f"{p.stem}.json").exists()
)


def normalise(text: str) -> str:
    """Strip each line, collapse runs of spaces, drop blank lines."""
    lines = (_SPACES.sub(" ", line.strip()) for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def split_legacy(rendered: str) -> list[tuple[str, str]]:
    """Split a legacy rendering into ``(role, normalised content)`` sections at the role markers."""
    sections: list[tuple[str, list[str]]] = [("user", [])]
    for line in rendered.splitlines():
        match = _MARKER.match(line.strip())
        if match:
            sections.append((match.group(1).lower(), []))
        else:
            sections[-1][1].append(line)
    out = [(role, normalise("\n".join(lines))) for role, lines in sections]
    return [(role, content) for role, content in out if content]


def drop_history_heading(name: str, sections: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Remove the old history heading line from the legacy system messages (intended difference 8)."""
    heading = LEGACY_HISTORY_HEADINGS.get(name)
    if heading is None:
        return sections
    out = []
    for role, content in sections:
        if role == "system":
            content = "\n".join(line for line in content.split("\n") if line != heading)
        out.append((role, content))
    return [(role, content) for role, content in out if content]


def join_lines(content: str) -> str:
    """Drop all whitespace of normalised content (``glued_lines`` cases).

    Where an old line was glued to the next one, the space kept at the joint differs from the line
    break of the .skye output, so the comparison ignores whitespace; the text and its order must
    still match exactly.
    """
    return "".join(content.split())


def parse_case(
    case: Any,
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]], str, bool]:
    """Return ``(variables, history, note, glued_lines)`` for one case (see the docstring)."""
    assert isinstance(case, dict), f"each case must be a JSON object, got {type(case).__name__}"
    if isinstance(case.get("variables"), dict):
        unknown = set(case) - {"variables", "history", "note", "glued_lines", "skye_variables"}
        assert not unknown, f"unknown keys in wrapped case: {sorted(unknown)}"
        history = case.get("history") or {}
        assert isinstance(history, dict), "'history' must map a name to a list of messages"
        glued = case.get("glued_lines", False)
        assert isinstance(glued, bool), "'glued_lines' must be true or false"
        return dict(case["variables"]), dict(history), str(case.get("note", "")), glued
    return dict(case), {}, "", False


#: Templates whose memories were sections of their own in the legacy text and are the standard section
#: of ``common/memories.skye`` now: a case with memory items is not compared with the legacy rendering.
MEMORIES_IN_THE_STANDARD_SECTION = ("agent_memory_assistant", "agent_memory_recall")
MEMORY_KINDS = (
    "episodic_memory",
    "semantic_memory",
    "procedural_memory",
    "persona_memory",
    "working_memory",
)


def _cases(name: str) -> list[Any]:
    path = CASES_DIR / f"{name}.json"
    if not path.exists():
        pytest.fail(
            f"{name}.skye exists but its case file {path.relative_to(REPO_ROOT)} is missing"
        )
    cases = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(cases, list) and cases, f"{path.name} must be a non-empty JSON list of cases"
    return cases


def test_intended_differences_are_listed() -> None:
    assert INTENDED_DIFFERENCES
    assert all(isinstance(item, str) and item for item in INTENDED_DIFFERENCES)


def test_every_legacy_rendering_has_its_skye_prompt_and_one_text_per_case() -> None:
    for legacy in LEGACY_DIR.glob("*.json"):
        assert (template_path(legacy.stem)).exists(), f"{legacy.stem}.skye is missing"
        texts = json.loads(legacy.read_text(encoding="utf-8"))
        assert len(texts) == len(_cases(legacy.stem)), f"{legacy.name}: one text per case"


def test_split_legacy_markers() -> None:
    text = "intro\n[SYSTEM]\n  You  are   X.\n\n[USER]\n\n[ASSISTANT]\nHi\n[USER]\nQ"
    assert split_legacy(text) == [
        ("user", "intro"),
        ("system", "You are X."),
        ("assistant", "Hi"),
        ("user", "Q"),
    ]


def test_join_lines_matches_glued_legacy_output() -> None:
    legacy = normalise("- I like tea (2024-01-01)- I live in Rome\n## Next")
    new = normalise("  - I like tea (2024-01-01)\n  - I live in Rome\n## Next")
    assert legacy != new
    assert join_lines(legacy) == join_lines(new)


@pytest.mark.parametrize(
    "name",
    SKYE_NAMES or [pytest.param("<none>", marks=pytest.mark.skip(reason="no .skye templates yet"))],
)
def test_skye_matches_legacy(name: str) -> None:
    legacy_path = LEGACY_DIR / f"{name}.json"
    legacy_texts = json.loads(legacy_path.read_text(encoding="utf-8"))
    spec = load_template(template_path(name), name)

    for index, raw in enumerate(_cases(name)):
        variables, history, note, glued = parse_case(raw)
        if name in MEMORIES_IN_THE_STANDARD_SECTION and any(variables.get(k) for k in MEMORY_KINDS):
            continue  # the memories are the standard section now (task 24.6); test_templates_migrated pins its text
        expected = drop_history_heading(name, split_legacy(legacy_texts[index]))
        skye_variables = {**variables, **(raw.get("skye_variables") or {})}
        messages = render_prompt(spec, skye_variables, history=history or None)
        actual = [(m.role, normalise(m.content)) for m in messages]
        actual = [(role, content) for role, content in actual if content]
        if glued:
            expected = [(role, join_lines(content)) for role, content in expected]
            actual = [(role, join_lines(content)) for role, content in actual]
        label = f"{name} case {index}" + (f" ({note})" if note else "")
        assert actual == expected, f"{label}: .skye and legacy .jinja differ"
