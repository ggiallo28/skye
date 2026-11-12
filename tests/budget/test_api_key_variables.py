"""No module names the API-key variable of a provider outside its profile (task 6.3, Requirement 60.3).

The variable names are data: ``api_key_variables`` in the ``profile.toml`` of each provider. The code reads them through
``skye.base.api_keys``. This test scans the string constants of the code (the docstrings are documentation and are left out) and fails
when one looks like the name of an API-key variable.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "skye"
NAME = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*_API_KEY$")

# The credential sources of Azure and Google keep one constant for their own discovery chain (a key, a token, a certificate...). A test of
# ``tests/unit/plugins/test_builtin_profiles.py`` checks that each equals the variable of its profile. The list only shrinks.
KNOWN = {
    "auth/plugins/azure/source.py": {"AZURE_OPENAI_API_KEY"},
    "auth/plugins/google/source.py": {"GOOGLE_API_KEY"},
}


def _docstring_nodes(tree: ast.AST) -> set[int]:
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                found.add(id(first.value))
    return found


def names_in(source: str) -> list[tuple[int, str]]:
    """The string constants of ``source`` that look like an API-key variable, outside the docstrings: ``(line, name)``."""
    tree = ast.parse(source)
    skip = _docstring_nodes(tree)
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in skip
        and NAME.match(node.value)
    ]


def test_no_module_names_an_api_key_variable_outside_its_profile():
    found: dict[str, set[str]] = {}
    for path in sorted(SRC.rglob("*.py")):
        names = {name for _, name in names_in(path.read_text(encoding="utf-8"))}
        if names:
            found[path.relative_to(SRC).as_posix()] = names
    unknown = {file: names for file, names in found.items() if names - KNOWN.get(file, set())}
    assert not unknown, (
        "an API-key variable is named in the code; put it in `api_key_variables` of the profile and read it through "
        f"`skye.base.api_keys`: {unknown}"
    )


def test_the_known_files_still_need_their_entry():
    stale = [
        file
        for file, names in KNOWN.items()
        if not names <= {n for _, n in names_in((SRC / file).read_text(encoding="utf-8"))}
    ]
    assert not stale, f"the constant is gone, remove the entry from KNOWN: {stale}"


def test_the_scanner_finds_a_variable_and_leaves_a_docstring_alone():
    code = '"""Reads ``OPENAI_API_KEY``."""\n\nKEY = "OPENAI_API_KEY"\n\n\ndef f():\n    """Uses ``X_API_KEY``."""\n    return "other"\n'
    assert names_in(code) == [(3, "OPENAI_API_KEY")]
    assert names_in('x = "api_key"\ny = "NOT_A_KEY"\n') == []
