"""No module of the code holds a cloud region as a default (task 6.6, Requirement 59.6).

A region comes from the caller, the authenticator or the variables of the profile, and when none is
found the library raises: there is no
``us-east-1`` in the code. The test scans the string constants (docstrings are documentation and are
left out) for the shape of a region.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "skye"
REGION = re.compile(r"^(?:us|eu|ap|sa|ca|me|af|il|mx|cn|us-gov)(?:-[a-z]+)+-\d$")

# Files that may hold a region literal, with the reason. The list only shrinks.
KNOWN: dict[str, str] = {}


def _docstring_nodes(tree: ast.AST) -> set[int]:
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                found.add(id(first.value))
    return found


def regions_in(source: str) -> list[tuple[int, str]]:
    """The string constants of ``source`` that look like a cloud region, outside the docstrings:
    ``(line, value)``."""
    tree = ast.parse(source)
    skip = _docstring_nodes(tree)
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in skip
        and REGION.match(node.value)
    ]


def test_no_module_holds_a_region_as_a_default():
    found = {
        path.relative_to(SRC).as_posix(): regions_in(path.read_text(encoding="utf-8"))
        for path in sorted(SRC.rglob("*.py"))
    }
    found = {file: hits for file, hits in found.items() if hits and file not in KNOWN}
    assert (
        not found
    ), f"a region is written in the code; it must come from the caller or the profile: {found}"


def test_the_known_files_still_need_their_entry():
    stale = [file for file in KNOWN if not regions_in((SRC / file).read_text(encoding="utf-8"))]
    assert not stale, f"no region is left in these files, remove them from KNOWN: {stale}"


def test_the_scanner_finds_a_region_and_leaves_a_docstring_and_a_name_alone():
    code = (
        '"""Region ``us-east-1``."""\n\nDEFAULT = "us-east-1"\n\n\ndef f(region="eu-west-2"):\n '
        '   """``ap-south-1``."""\n    return "region-name"\n'
    )
    assert regions_in(code) == [(3, "us-east-1"), (6, "eu-west-2")]
    assert regions_in('x = "us-gov-west-1"\ny = "name"\n') == [(1, "us-gov-west-1")]
