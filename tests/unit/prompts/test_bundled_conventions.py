"""Conventions every bundled ``.skye`` prompt and every example ``.skye`` file follows.

- front matter with ``title``, ``description``, ``version`` and ``tags``;
- a prompt file ends with a usage-example doc comment whose ``builder.render("<name>", {...})``
  dictionary (pure Python literals) renders;
- comments: ``/** ... **/`` documents, ``#`` short notes (at most 2 lines in a row), no plain
  ``/* ... */``;
- the shared variable shapes (``tools`` and the memories) are declared exactly as below;
- the removed names (``chat_history`` ...) are not declared;
- every variable has a description, every field of a structured variable a type.
"""

from __future__ import annotations

import ast
import re
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from skye.base.dsl import build
from skye.base.dsl.build import Document
from skye.prompts import BasePromptBuilder
from skye.utils.skye_files import file_resolver
from skye.prompts.skye_prompts import load_prompt, render_prompt

ROOT = Path(__file__).resolve().parents[3]
BUNDLED = sorted((ROOT / "src" / "skye" / "prompts" / "templates").glob("*.skye"))
# the gallery has its own test (test_catalogue_gallery.py): its files carry no example comment (D118);
# the files of `shared_parts` are a multi-file example (a partial and two prompts): the runner
# `examples/prompts/shared_parts.py` renders them (tests/examples) and `skye check` passes on each
EXAMPLES = sorted(
    p
    for p in (ROOT / "examples").rglob("*.skye")
    if "catalogue" not in p.parts and "shared_parts" not in p.parts
)
FILES = BUNDLED + EXAMPLES


def _id(path: Path) -> str:
    return str(path.relative_to(ROOT))


#: The shared shapes (the same text as the prompt docs); ``shapes_id`` is the variant of the three
#: memory-editing agents, whose memory items also carry an ``id``.
REFERENCE = """
prompt "shapes" {
  variables = {
    tools             = list({
                          name        = string                "Tool name"
                          description = string                "What the tool does"
                          parameters  = map({})               "Arguments: name to type or description"
                          returns     = string("")            "What the tool returns"
                        }, [])                                "Tools the agent may call"
    persona_memory    = list({
                          content = string                    "What is known about the user or the agent"
                          source  = string("")                "Where it comes from"
                        }, [])                                "Who the user and the agent are"
    episodic_memory   = list({
                          content   = string                  "What happened"
                          timestamp = string("")              "When it happened"
                          source    = string("")              "Where it comes from"
                        }, [])                                "Past events"
    semantic_memory   = list({
                          content = string                    "The fact"
                          source  = string("")                "Where it comes from"
                        }, [])                                "Known facts"
    procedural_memory = list({
                          name    = string("")                "Procedure name"
                          content = string("")                "How to do it, as text"
                          steps   = list(string, [])          "How to do it, as steps"
                        }, [])                                "Procedures that worked"
    working_memory    = list({
                          content = string                    "The note"
                        }, [])                                "Notes for the current task"
  }
  message "user" { text = "x" }
}

prompt "shapes_id" {
  variables = {
    persona_memory    = list({
                          id      = string("")                "Item id, to update or delete it"
                          content = string                    "What is known about the user or the agent"
                          source  = string("")                "Where it comes from"
                        }, [])                                "Who the user and the agent are"
    episodic_memory   = list({
                          id        = string("")              "Item id, to update or delete it"
                          content   = string                  "What happened"
                          timestamp = string("")              "When it happened"
                          source    = string("")              "Where it comes from"
                        }, [])                                "Past events"
    semantic_memory   = list({
                          id      = string("")                "Item id, to update or delete it"
                          content = string                    "The fact"
                          source  = string("")                "Where it comes from"
                        }, [])                                "Known facts"
    procedural_memory = list({
                          id      = string("")                "Item id, to update or delete it"
                          name    = string("")                "Procedure name"
                          content = string("")                "How to do it, as text"
                          steps   = list(string, [])          "How to do it, as steps"
                        }, [])                                "Procedures that worked"
    working_memory    = list({
                          id      = string("")                "Item id, to update or delete it"
                          content = string                    "The note"
                        }, [])                                "Notes for the current task"
  }
  message "user" { text = "x" }
}
"""

SHARED = ("tools", "persona_memory", "episodic_memory", "semantic_memory", "procedural_memory",
          "working_memory")  # fmt: skip
WITH_ID = {"agent_memory_update", "agent_memory_consolidation", "agent_memory_working"}
REMOVED = {"chat_history", "conversation_history", "declarative_memory", "procedural_memories",
           "procedures"}  # fmt: skip
FRONT_MATTER = ("title", "description", "version", "tags")
_TYPES = {"string", "number", "bool", "list", "map"}


@cache
def _reference() -> dict[str, dict[str, Any]]:
    document = build(REFERENCE)
    assert not document.diagnostics, [d.format() for d in document.diagnostics]
    return {
        name: {v.name: v for v in document.prompt(name).variables}
        for name in ("shapes", "shapes_id")
    }


@cache
def _document(path: Path) -> Document:
    return build(
        path.read_text(encoding="utf-8"),
        filename=str(path),
        resolver=file_resolver(path),  # a bundled template may include a partial of common/
        key=str(path.resolve()),
    )


def _built(path: Path) -> Document:
    document = _document(path)
    assert not document.diagnostics, [d.format() for d in document.diagnostics]
    return document


# -- comments ----------------------------------------------------------------------------------


def _comments(text: str) -> list[tuple[str, int, int, int]]:
    """``(text, start offset, end offset, line)`` of every comment, strings skipped like the lexer."""
    out: list[tuple[str, int, int, int]] = []
    i, n = 0, len(text)
    while i < n:
        if text.startswith("#", i):
            end = text.find("\n", i)
            end = n if end == -1 else end
            out.append((text[i:end], i, end, text.count("\n", 0, i) + 1))
            i = end
        elif text.startswith("/*", i):
            close = text.find("*/", i + 2)
            end = n if close == -1 else close + 2
            out.append((text[i:end], i, end, text.count("\n", 0, i) + 1))
            i = end
        elif text.startswith('"""', i):
            close = text.find('"""', i + 3)
            while close != -1 and text[close - 1] == "\\":
                close = text.find('"""', close + 1)
            i = n if close == -1 else close + 3
        elif text[i] == '"':
            j = i + 1
            while j < n and text[j] not in '"\n':
                j += 2 if text[j] == "\\" else 1
            i = j + 1
        else:
            i += 1
    return out


@pytest.mark.parametrize("path", FILES, ids=_id)
def test_no_plain_block_comment(path: Path) -> None:
    bad = [
        line
        for body, _, _, line in _comments(path.read_text(encoding="utf-8"))
        if body.startswith("/*") and not (body.startswith("/**") and body.endswith("**/"))
    ]
    assert not bad, f"plain /* */ comment at lines {bad}: use /** ... **/ or #"


@pytest.mark.parametrize("path", FILES, ids=_id)
def test_no_long_run_of_hash_comments(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    full = {line for body, _, _, line in _comments(text) if body.startswith("#")}
    full = {n for n in full if lines[n - 1].lstrip().startswith("#")}
    runs: list[int] = []
    run = 0
    for number in range(1, len(lines) + 2):
        if number in full:
            run += 1
            continue
        if run > 2:
            runs.append(number - run)
        run = 0
    assert not runs, f"more than 2 '#' lines in a row at lines {runs}: use a /** ... **/ block"


# -- front matter and usage example ------------------------------------------------------------


@pytest.mark.parametrize("path", FILES, ids=_id)
def test_front_matter(path: Path) -> None:
    metadata = _built(path).metadata or {}
    missing = [key for key in FRONT_MATTER if not metadata.get(key)]
    assert not missing, f"front matter lacks {missing}"


_GUTTER = re.compile(r"^\s*\*(?!\*/) ?", re.MULTILINE)


def _call_text(text: str, start: int) -> str:
    """The text of ``builder.render(...)`` from ``start`` to its matching ``)``."""
    depth, i, n = 0, start, len(text)
    while i < n:
        ch = text[i]
        if ch in "'\"":
            j = i + 1
            while j < n and text[j] != ch:
                j += 2 if text[j] == "\\" else 1
            i = j + 1
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
        i += 1
    raise AssertionError("builder.render( is not closed")


def _usage(path: Path) -> tuple[str, dict[str, Any]]:
    """The prompt name and the variables of the closing usage-example comment."""
    text = path.read_text(encoding="utf-8")
    comments = _comments(text)
    assert comments, "no comment: the file must end with a /** Example: ... **/ comment"
    body, _, end, _ = comments[-1]
    assert not text[end:].strip(), "the usage-example comment must be the last thing in the file"
    assert body.startswith("/**") and body.endswith("**/"), "the last comment is not /** ... **/"
    plain = _GUTTER.sub("", body[3:-3])
    start = plain.find("builder.render(")
    assert start != -1, 'the last comment has no builder.render("<name>", {...})'
    call = ast.parse(_call_text(plain, start + len("builder.render")), mode="eval").body
    assert isinstance(call, ast.Tuple) and len(call.elts) == 2, "render(name, {...}) expected"
    name = ast.literal_eval(call.elts[0])
    variables = ast.literal_eval(call.elts[1])
    assert isinstance(name, str) and isinstance(variables, dict)
    return name, variables


def _has_prompt(path: Path) -> bool:
    return bool(_document(path).prompts)


@pytest.mark.parametrize("path", BUNDLED, ids=_id)
def test_bundled_prompt_has_no_comment_and_has_a_sample(path: Path) -> None:
    """The examples left the bundled files (task 24.9): the sample variables are in ``examples/prompts/bundled``."""
    assert not _comments(path.read_text(encoding="utf-8")), "a bundled prompt keeps no comment"
    sample = ROOT / "examples" / "prompts" / "bundled" / f"{path.stem}.json"
    assert sample.is_file(), f"no sample variables for {path.stem}"


@pytest.mark.parametrize("path", [p for p in EXAMPLES if _has_prompt(p)], ids=_id)
def test_example_usage_example_renders(path: Path) -> None:
    name, variables = _usage(path)
    spec = load_prompt(path.read_text(encoding="utf-8"), name)
    assert render_prompt(spec, variables)


# -- variables ---------------------------------------------------------------------------------


def _variables(path: Path) -> list[tuple[str, Any]]:
    return [(p.name, v) for p in _built(path).prompts for v in p.variables]


def _prompt_files() -> list[Path]:
    return [p for p in FILES if _has_prompt(p)]


@pytest.mark.parametrize("path", _prompt_files(), ids=_id)
def test_shared_shapes(path: Path) -> None:
    reference = _reference()["shapes_id"]  # every template takes the memories from common/memories.skye: with the optional id
    wrong = []
    for prompt, var in _variables(path):
        if var.name in SHARED:
            expected = reference.get(var.name, _reference()["shapes"][var.name])
            if var != expected:
                wrong.append(f"{prompt}.{var.name}")
    assert not wrong, f"not the shared shape: {wrong}"


@pytest.mark.parametrize("path", _prompt_files(), ids=_id)
def test_no_removed_names(path: Path) -> None:
    found = [f"{prompt}.{var.name}" for prompt, var in _variables(path) if var.name in REMOVED]
    assert not found, f"removed names (use semantic_memory / procedural_memory / history): {found}"


def _untyped(fields: list[Any], path: str) -> list[str]:
    bad: list[str] = []
    for f in fields:
        where = f"{path}.{f.name}"
        if f.type not in _TYPES or (f.type == "list" and f.item_type not in _TYPES):
            bad.append(where)
        bad.extend(_untyped(f.fields, where))
    return bad


@pytest.mark.parametrize("path", _prompt_files(), ids=_id)
def test_variables_are_described_and_typed(path: Path) -> None:
    undescribed = [f"{p}.{v.name}" for p, v in _variables(path) if not v.description]
    untyped = [
        bad for p, v in _variables(path) if v.structured for bad in _untyped(v.fields, f"{p}.{v.name}")
    ]
    assert not undescribed, f"variables without a description: {undescribed}"
    assert not untyped, f"fields without a type: {untyped}"
