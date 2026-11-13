"""No docstring of ``src/skye`` carries a reference to a requirement, a decision, an open decision
or a task (task 24.4).

A docstring says what the library does. Where a piece of code answers a requirement or a decision,
that is a comment above the
definition, and the wheel does not ship comments (task 24.3). ``KNOWN`` lists the files that still
carry a reference in a docstring,
with how many lines; it can only shrink.
"""

from __future__ import annotations

import ast
import re

from tests.budget.measure import ROOT

SRC = ROOT / "src" / "skye"
NUM = r"\d+(?:\.\d+)*"
REFERENCE = re.compile(
    rf"Requirements?\s+{NUM}|(?<![\w`])D\d{{2,3}}\b|(?<![\w`])O\d{{2,3}}\b|(?<![\w`])[a-z][a-z0-9-]*:\d+\.\d+|\btasks?\s+{NUM}"
)

# : File (relative to ``src/skye``) to the number of docstring lines that still hold a reference. A
# listed file that no longer needs its entry fails.
KNOWN: dict[str, int] = {
    # The wheel keeps every file of the templates folder as it is, so a comment there would be
    # shipped (see ``hatch_build.py``).
    "prompts/templates/__init__.py": 1,
}


def reference_lines(source: str) -> int:
    """How many lines of the docstrings of ``source`` hold a reference."""
    count = 0
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            count += sum(1 for line in (doc or "").split("\n") if REFERENCE.search(line))
    return count


def test_the_scanner_sees_a_reference_and_ignores_the_rest():
    assert reference_lines('"""Does a thing (Requirement 5.2, D110)."""') == 1
    assert reference_lines('def f():\n    """See O63."""\n') == 1
    assert reference_lines('"""Does a thing."""\n# Requirement 5.2, D110\n') == 0
    assert reference_lines('x = "Requirement 5.2"\n"""Reads http://host:8080 and AWS_D1."""') == 0


def test_no_docstring_holds_a_reference_outside_the_known_list():
    found = {}
    for path in sorted(SRC.rglob("*.py")):
        lines = reference_lines(path.read_text())
        if lines:
            found[path.relative_to(SRC).as_posix()] = lines
    extra = {name: n for name, n in found.items() if n > KNOWN.get(name, 0)}
    assert (
        not extra
    ), f"references in docstrings (move them to a comment above the definition): {extra}"
    stale = {name: n for name, n in KNOWN.items() if found.get(name, 0) < n}
    assert not stale, f"entries of KNOWN that are no longer needed (lower or remove them): {stale}"
