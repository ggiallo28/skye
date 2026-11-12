"""Deterministic guard on the steering decisions (see .agents/prompts/done/02-steering.md).

Offline and deterministic: parses the steering files under .kiro/steering and asserts that
the binding project decisions are present, that no file reinstates pydantic as the
data-structure standard, that always-included files stay within their line budget (and the
always-on total stays small), and that every fileMatch file declares a pattern.

This file is owned (see .github/CODEOWNERS, which covers tests/budget/). Removing or
weakening a decision requires editing this test in a reviewed, owner-approved pull request;
it cannot be done by silently rewording a steering file.
"""

from __future__ import annotations

import re

from tests.budget.measure import ROOT

STEERING = ROOT / ".kiro" / "steering"

# Supported Kiro inclusion modes.
VALID_INCLUSION = {"always", "fileMatch", "manual", "auto"}

# Always-included files and their maximum line counts. The sum is the always-on budget a
# developer pays in every conversation; keep it small.
ALWAYS_BUDGETS = {
    "00-rules.md": 80,
}
ALWAYS_TOTAL_MAX = 80

# fileMatch files that must declare a pattern.
FILEMATCH_FILES = {
    "20-repo.md",
    "30-code.md",
}

# Each decision must survive as a recognizable anchor in some steering file. If a decision
# string disappears, the test fails: the decision cannot be dropped by a quiet edit.
# (anchor regex, human description)
REQUIRED_DECISIONS = [
    (r"serverless", "serverless-first deployment"),
    (r"serverless architectures", "serverless architectures where size and cold start matter"),
    (r"cold start", "cold start as a cost of the library"),
    (r"budgets\.toml", "budgets governed by budgets.toml"),
    (r"only (go|goes|shrink)|may only shrink", "budgets only go down"),
    (r"lazil|LazyImporter", "lazy imports for heavy/optional libraries"),
    (r"standard library", "stdlib-first dependency order"),
    (r"compiled", "no compiled package in the core"),
    (r"single package|one package", "one package with extras"),
    (r"MIT", "MIT licence"),
    (r"LiteLLM", "no-copy / LiteLLM enterprise rule"),
    (r"dataclass", "dataclasses, not pydantic"),
    (r"Runnable", "composition via the Runnable Port"),
    (r"four layers|ordinal", "four-layer import direction"),
    (r"Capability, not Tool|Capability.*never.*Tool", "capability terminology"),
    (r"LangChain", "avoid LangChain-style names"),
    (r"codename", "codename watermark rule"),
    (r"requirements .*design.*tasks|requirements\s*→\s*design\s*→\s*tasks",
     "spec-driven requirements/design/tasks order"),
    (r"MCP is \*\*client-only\*\*|client-only", "MCP client-only"),
    (r'impl="skyemcp"', "MCP skyemcp default, fastmcp opt-in"),
    (r"authentication.*authoriz|auth.*authoriz", "auth vs policy contrast"),
]


def _files() -> list:
    return sorted(p for p in STEERING.glob("*.md"))


def _front_matter(text: str) -> dict[str, str]:
    """Parse the leading --- front-matter block into a flat dict (deterministic, no yaml)."""
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        return {}
    out: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip().strip("'\"")
    return out


def _all_text() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in _files())


def test_every_file_has_a_valid_inclusion_mode():
    bad = []
    for path in _files():
        fm = _front_matter(path.read_text(encoding="utf-8"))
        mode = fm.get("inclusion")
        if mode not in VALID_INCLUSION:
            bad.append(f"{path.name}: inclusion '{mode}' is not one of {sorted(VALID_INCLUSION)}")
    assert not bad, "\n".join(bad)


def test_filematch_files_declare_a_pattern():
    bad = []
    for path in _files():
        fm = _front_matter(path.read_text(encoding="utf-8"))
        if fm.get("inclusion") == "fileMatch" and not fm.get("fileMatchPattern"):
            bad.append(f"{path.name}: inclusion is fileMatch but no fileMatchPattern declared")
    assert not bad, "\n".join(bad)


def test_expected_filematch_files_are_filematch():
    bad = []
    for name in sorted(FILEMATCH_FILES):
        path = STEERING / name
        assert path.exists(), f"missing steering file: {name}"
        fm = _front_matter(path.read_text(encoding="utf-8"))
        if fm.get("inclusion") != "fileMatch":
            bad.append(f"{name}: expected inclusion fileMatch, found {fm.get('inclusion')}")
    assert not bad, "\n".join(bad)


def test_always_included_files_stay_within_line_budget():
    bad = []
    total = 0
    for name, budget in ALWAYS_BUDGETS.items():
        path = STEERING / name
        assert path.exists(), f"missing always-on steering file: {name}"
        fm = _front_matter(path.read_text(encoding="utf-8"))
        assert fm.get("inclusion") == "always", f"{name}: expected inclusion always"
        lines = path.read_text(encoding="utf-8").count("\n") + 1
        total += lines
        if lines > budget:
            bad.append(f"{name}: {lines} lines > budget {budget}")
    assert not bad, "\n".join(bad)
    assert total <= ALWAYS_TOTAL_MAX, (
        f"always-on steering totals {total} lines > {ALWAYS_TOTAL_MAX}. Steering read in every "
        "conversation must stay small; move detail to a fileMatch file, a spec, or the docs wiki."
    )


def test_no_file_reinstates_pydantic_as_the_standard():
    """The dataclasses decision is locked: no steering file may make pydantic the standard."""
    offenders = []
    allowed = re.compile(r"not pydantic|no (new )?pydantic|pydantic.*(leaving|removed|legacy|migrat)",
                         re.IGNORECASE)
    make_standard = re.compile(
        r"use pydantic for all|pydantic for all data|all data structures.*pydantic", re.IGNORECASE
    )
    for path in _files():
        text = path.read_text(encoding="utf-8")
        for m in make_standard.finditer(text):
            window = text[max(0, m.start() - 40): m.end() + 40]
            if not allowed.search(window):
                offenders.append(f"{path.name}: '{m.group(0)}'")
    assert not offenders, (
        "Steering reinstates pydantic as the data-structure standard: "
        + "; ".join(offenders)
        + ". New data structures use dataclasses (00-rules.md)."
    )


def test_all_binding_decisions_are_present():
    text = _all_text()
    missing = [desc for pattern, desc in REQUIRED_DECISIONS
               if not re.search(pattern, text, re.IGNORECASE)]
    assert not missing, (
        "Binding decisions missing from steering (anchor not found): "
        + "; ".join(missing)
        + ". A decision may only be removed by a reviewed, owner-approved change to this test."
    )


def test_language_preferences_file_removed():
    """Steering is English-only; the Italian language-preferences file must not return."""
    assert not (STEERING / "language-preferences.md").exists(), (
        "language-preferences.md is back. Steering is English-only by decision."
    )


def test_requirement_headings_follow_the_kiro_syntax_and_are_sequential():
    """Requirements are `### Requirement N: <title>`, numbered 1..n with no gaps; each has a user story and numbered criteria.

    Specs cite `Requirement N.k` and tools fetch a requirement by grepping its heading, so the heading syntax is Kiro's.
    """
    text = (STEERING / "10-requirements.md").read_text(encoding="utf-8")
    sections = re.split(r"(?m)^### Requirement ", text)[1:]
    assert sections, "no requirements found"
    bad: list[str] = []
    for expected, sec in enumerate(sections, 1):
        head = re.match(r"(\d+): \S", sec)
        if not head or int(head.group(1)) != expected:
            bad.append(f"heading {expected}: expected '### Requirement {expected}: <title>'")
            continue
        if "**User Story:**" not in sec:
            bad.append(f"Requirement {expected}: no user story")
        crit = re.findall(r"(?m)^(\d+)\. ", sec.split("#### Acceptance Criteria", 1)[-1])
        if crit != [str(i) for i in range(1, len(crit) + 1)] or not crit:
            bad.append(f"Requirement {expected}: criteria are not numbered 1..n")
    assert not bad, "; ".join(bad)
